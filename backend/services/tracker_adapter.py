"""Provider-isolated, read-only external tracker adapters (Story 3.3, AD-7)."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlparse

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


class TrackerReferenceError(TrackerAdapterError):
    """Raised when a provider-specific external or ticket reference is invalid."""


class TrackerAdapterInterface(Protocol):
    async def test_connection(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
    ) -> None: ...

    async def fetch_tickets(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
    ) -> list[TrackerTicket]: ...

    async def write(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
        ticket_ref: str,
        action: str,
        value: str,
    ) -> None: ...


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

    async def _request_no_content(self, method: str, url: str, **kwargs: Any) -> None:
        try:
            response = await self._client.request(method, url, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TrackerAdapterError("Tracker provider write failed") from exc

    async def test_connection(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
    ) -> None:
        await self.fetch_tickets(base_url=base_url, external_ref=external_ref, token=token)  # type: ignore[attr-defined]


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
                ... on Issue { number title url repository { nameWithOwner } }
                ... on PullRequest { number title url repository { nameWithOwner } }
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
                ... on Issue { number title url repository { nameWithOwner } }
                ... on PullRequest { number title url repository { nameWithOwner } }
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
            raise TrackerReferenceError("GitHub external ref must use owner/project-number")

        payload = await self._request_json(
            "POST",
            f"{base_url.rstrip('/')}/graphql",
            headers={"Authorization": "Bearer " + token},
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
            number = content.get("number")
            repository = content.get("repository")
            name_with_owner = (
                repository.get("nameWithOwner")
                if isinstance(repository, dict)
                else None
            )
            if not name_with_owner and number and content.get("url"):
                parts = urlparse(str(content["url"])).path.strip("/").split("/")
                if len(parts) >= 4 and parts[-2] in {"issues", "pull"}:
                    name_with_owner = "/".join(parts[:2])
            ticket_id = (
                f"{name_with_owner}#{number}"
                if name_with_owner and number
                else str(number or node.get("id") or "")
            )
            tickets.append(
                TrackerTicket(
                    id=ticket_id,
                    title=str(content.get("title") or "Untitled"),
                    status=str(status.get("name") if isinstance(status, dict) else "No status"),
                    url=str(content["url"]) if content.get("url") else None,
                )
            )
        return tickets

    async def write(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
        ticket_ref: str,
        action: str,
        value: str,
    ) -> None:
        del external_ref
        match = re.fullmatch(r"([^/\s]+)/([^#/\s]+)#(\d+)", ticket_ref)
        if match is None:
            raise TrackerReferenceError("GitHub ticket ref must use owner/repository#number")
        owner, repo, issue_number = match.groups()
        issue_url = (
            f"{base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
            f"{quote(repo, safe='')}/issues/{issue_number}"
        )
        headers = {
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
        }
        if action == "comment":
            await self._request_no_content(
                "POST",
                f"{issue_url}/comments",
                headers=headers,
                json={"body": value},
            )
            return
        if action == "transition":
            state = {
                "open": "open",
                "reopen": "open",
                "reopened": "open",
                "close": "closed",
                "closed": "closed",
                "done": "closed",
            }.get(value.strip().lower())
            if state is None:
                raise TrackerAdapterError("GitHub transition must target open or closed")
            await self._request_no_content(
                "PATCH",
                issue_url,
                headers=headers,
                json={"state": state},
            )
            return
        raise TrackerAdapterError(f"Unsupported tracker write action: {action}")


class JiraTrackerAdapter(_HttpTrackerAdapter):
    """Read Jira project issues through the REST API v3 enhanced search."""

    async def fetch_tickets(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
    ) -> list[TrackerTicket]:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{1,19}", external_ref) is None:
            raise TrackerReferenceError("Jira external ref must be an uppercase project key")
        escaped_ref = external_ref.replace("\\", "\\\\").replace('"', '\\"')
        payload = await self._request_json(
            "GET",
            f"{base_url.rstrip('/')}/rest/api/3/search/jql",
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
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

    async def write(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
        ticket_ref: str,
        action: str,
        value: str,
    ) -> None:
        del external_ref
        if re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", ticket_ref) is None:
            raise TrackerReferenceError("Jira ticket ref must use PROJECT-123")
        issue_url = f"{base_url.rstrip('/')}/rest/api/3/issue/{quote(ticket_ref, safe='-')}"
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if action == "comment":
            await self._request_no_content(
                "POST",
                f"{issue_url}/comment",
                headers=headers,
                json={
                    "body": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": value}],
                            }
                        ],
                    }
                },
            )
            return
        if action == "transition":
            payload = await self._request_json(
                "GET",
                f"{issue_url}/transitions",
                headers=headers,
            )
            transitions = payload.get("transitions")
            if not isinstance(transitions, list):
                raise TrackerAdapterError("Jira returned invalid transitions")
            transition_id = next(
                (
                    str(item["id"])
                    for item in transitions
                    if isinstance(item, dict)
                    and item.get("id") is not None
                    and str(item.get("name", "")).casefold() == value.strip().casefold()
                ),
                None,
            )
            if transition_id is None:
                raise TrackerAdapterError(f"Jira transition '{value}' is unavailable")
            await self._request_no_content(
                "POST",
                f"{issue_url}/transitions",
                headers=headers,
                json={"transition": {"id": transition_id}},
            )
            return
        raise TrackerAdapterError(f"Unsupported tracker write action: {action}")


class AzureDevOpsTrackerAdapter(_HttpTrackerAdapter):
    """Read Azure DevOps work items using WIQL 7.1."""

    async def fetch_tickets(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
    ) -> list[TrackerTicket]:
        if not external_ref.strip() or any(char in external_ref for char in "\\/#?"):
            raise TrackerReferenceError("Azure DevOps external ref must be a project name")
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

    async def write(
        self,
        *,
        base_url: str,
        external_ref: str,
        token: str,
        ticket_ref: str,
        action: str,
        value: str,
    ) -> None:
        if not ticket_ref.isdigit():
            raise TrackerReferenceError("Azure DevOps ticket ref must be a numeric work item ID")
        auth = base64.b64encode(f":{token}".encode()).decode()
        project_url = f"{base_url.rstrip('/')}/{quote(external_ref, safe='')}"
        headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
        if action == "comment":
            await self._request_no_content(
                "POST",
                f"{project_url}/_apis/wit/workItems/{ticket_ref}/comments",
                headers=headers,
                params={"api-version": "7.1-preview.4"},
                json={"text": value},
            )
            return
        if action == "transition":
            await self._request_no_content(
                "PATCH",
                f"{project_url}/_apis/wit/workitems/{ticket_ref}",
                headers={**headers, "Content-Type": "application/json-patch+json"},
                params={"api-version": "7.1"},
                json=[{"op": "add", "path": "/fields/System.State", "value": value}],
            )
            return
        raise TrackerAdapterError(f"Unsupported tracker write action: {action}")


def build_tracker_adapters(client: httpx.AsyncClient) -> dict[str, TrackerAdapterInterface]:
    return {
        "github": GitHubProjectsTrackerAdapter(client),
        "jira": JiraTrackerAdapter(client),
        "azure_devops": AzureDevOpsTrackerAdapter(client),
    }
