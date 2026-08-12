"""Provider-isolated, read-only external tracker adapters (Story 3.3, AD-7)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx


@dataclass(frozen=True)
class TrackerTicket:
    """Provider-neutral ticket state persisted by the tracker sync read model."""

    id: str
    title: str
    status: str
    url: str | None


class TrackerAdapterError(RuntimeError):
    """Raised when provider input, transport, or response data is invalid."""


class TrackerAdapterInterface(Protocol):
    async def fetch_tickets(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
    ) -> list[TrackerTicket]: ...


class _HttpTrackerAdapter:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, url, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TrackerAdapterError("Tracker provider request failed") from exc
        if not isinstance(payload, dict):
            raise TrackerAdapterError("Tracker provider returned an invalid response")
        return payload


class GitHubProjectsTrackerAdapter(_HttpTrackerAdapter):
    """Read GitHub Projects v2 items through the GraphQL API."""

    _QUERY = """
    query TrackerProject($owner: String!, $number: Int!) {
      organization(login: $owner) {
        projectV2(number: $number) {
          items(first: 100) {
            nodes {
              id
              content {
                ... on Issue { number title url }
                ... on PullRequest { number title url }
                ... on DraftIssue { title }
              }
              status: fieldValueByName(name: "Status") {
                ... on ProjectV2ItemFieldSingleSelectValue { name }
              }
            }
          }
        }
      }
      user(login: $owner) {
        projectV2(number: $number) {
          items(first: 100) {
            nodes {
              id
              content {
                ... on Issue { number title url }
                ... on PullRequest { number title url }
                ... on DraftIssue { title }
              }
              status: fieldValueByName(name: "Status") {
                ... on ProjectV2ItemFieldSingleSelectValue { name }
              }
            }
          }
        }
      }
    }
    """

    async def fetch_tickets(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
    ) -> list[TrackerTicket]:
        owner, separator, raw_number = external_ref.partition("/")
        if not separator or not owner or not raw_number.isdigit():
            raise TrackerAdapterError("GitHub external ref must use owner/project-number")

        payload = await self._request_json(
            "POST",
            f"{base_url.rstrip('/')}/graphql",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "query": self._QUERY,
                "variables": {"owner": owner, "number": int(raw_number)},
            },
        )
        if payload.get("errors"):
            raise TrackerAdapterError("GitHub Projects query failed")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise TrackerAdapterError("GitHub Projects returned an invalid response")
        owner_data = data.get("organization") or data.get("user")
        if not isinstance(owner_data, dict):
            raise TrackerAdapterError("GitHub Project was not found")
        try:
            nodes = owner_data["projectV2"]["items"]["nodes"]
        except (KeyError, TypeError) as exc:
            raise TrackerAdapterError("GitHub Project was not found") from exc
        if not isinstance(nodes, list):
            raise TrackerAdapterError("GitHub Projects returned invalid items")

        tickets: list[TrackerTicket] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            content = node.get("content")
            if not isinstance(content, dict):
                continue
            status = node.get("status")
            tickets.append(
                TrackerTicket(
                    id=str(content.get("number") or node.get("id") or ""),
                    title=str(content.get("title") or "Untitled"),
                    status=str(status.get("name") if isinstance(status, dict) else "No status"),
                    url=str(content["url"]) if content.get("url") else None,
                )
            )
        return tickets


class JiraTrackerAdapter(_HttpTrackerAdapter):
    """Read Jira project issues through the REST API v3 enhanced search."""

    async def fetch_tickets(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
    ) -> list[TrackerTicket]:
        escaped_ref = external_ref.replace("\\", "\\\\").replace('"', '\\"')
        payload = await self._request_json(
            "GET",
            f"{base_url.rstrip('/')}/rest/api/3/search/jql",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={
                "jql": f'project = "{escaped_ref}" ORDER BY updated DESC',
                "fields": "summary,status",
                "maxResults": 100,
            },
        )
        issues = payload.get("issues")
        if not isinstance(issues, list):
            raise TrackerAdapterError("Jira returned invalid issues")

        tickets: list[TrackerTicket] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            fields = issue.get("fields")
            if not isinstance(fields, dict):
                continue
            key = str(issue.get("key") or issue.get("id") or "")
            status = fields.get("status")
            tickets.append(
                TrackerTicket(
                    id=key,
                    title=str(fields.get("summary") or "Untitled"),
                    status=str(status.get("name") if isinstance(status, dict) else "Unknown"),
                    url=f"{base_url.rstrip('/')}/browse/{quote(key, safe='-')}",
                )
            )
        return tickets


class AzureDevOpsTrackerAdapter(_HttpTrackerAdapter):
    """Read Azure DevOps work items using WIQL 7.1."""

    async def fetch_tickets(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
    ) -> list[TrackerTicket]:
        auth = base64.b64encode(f":{token}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
        }
        project_url = f"{base_url.rstrip('/')}/{quote(external_ref, safe='')}"
        query_result = await self._request_json(
            "POST",
            f"{project_url}/_apis/wit/wiql",
            headers=headers,
            params={"api-version": "7.1", "$top": 100},
            json={
                "query": (
                    "SELECT [System.Id], [System.Title], [System.State] "
                    "FROM WorkItems ORDER BY [System.ChangedDate] DESC"
                )
            },
        )
        references = query_result.get("workItems")
        if not isinstance(references, list):
            raise TrackerAdapterError("Azure DevOps returned invalid work item references")
        ids = [str(item["id"]) for item in references if isinstance(item, dict) and item.get("id") is not None]
        if not ids:
            return []

        item_result = await self._request_json(
            "GET",
            f"{project_url}/_apis/wit/workitems",
            headers=headers,
            params={
                "ids": ",".join(ids),
                "fields": "System.Id,System.Title,System.State",
                "api-version": "7.1",
            },
        )
        items = item_result.get("value")
        if not isinstance(items, list):
            raise TrackerAdapterError("Azure DevOps returned invalid work items")

        tickets: list[TrackerTicket] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            fields = item.get("fields")
            if not isinstance(fields, dict):
                continue
            tickets.append(
                TrackerTicket(
                    id=str(item.get("id") or ""),
                    title=str(fields.get("System.Title") or "Untitled"),
                    status=str(fields.get("System.State") or "Unknown"),
                    url=str(item["url"]) if item.get("url") else None,
                )
            )
        return tickets


def build_tracker_adapters(client: httpx.AsyncClient) -> dict[str, TrackerAdapterInterface]:
    return {
        "github": GitHubProjectsTrackerAdapter(client),
        "jira": JiraTrackerAdapter(client),
        "azure_devops": AzureDevOpsTrackerAdapter(client),
    }
