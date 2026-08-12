from __future__ import annotations

import json

import httpx
import pytest

from backend.services.tracker_adapter import (
    AzureDevOpsTrackerAdapter,
    GitHubProjectsTrackerAdapter,
    JiraTrackerAdapter,
    TrackerAdapterError,
    TrackerTicket,
)


@pytest.mark.asyncio
async def test_github_projects_normalizes_issue_and_draft_items() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graphql"
        assert request.headers["authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload["variables"] == {"owner": "acme", "number": 7}
        return httpx.Response(
            200,
            json={
                "data": {
                    "organization": {
                        "projectV2": {
                            "items": {
                                "nodes": [
                                    {
                                        "id": "item-1",
                                        "content": {
                                            "number": 12,
                                            "title": "Fix checkout",
                                            "url": "https://github.com/acme/shop/issues/12",
                                        },
                                        "status": {"name": "In progress"},
                                    },
                                    {
                                        "id": "item-2",
                                        "content": {"title": "Draft card"},
                                        "status": None,
                                    },
                                ]
                            }
                        }
                    },
                    "user": None,
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.github.com") as client:
        tickets = await GitHubProjectsTrackerAdapter(client).fetch_tickets(
            base_url="https://api.github.com",
            external_ref="acme/7",
            token="secret",
        )

    assert tickets == [
        TrackerTicket(
            id="12",
            title="Fix checkout",
            status="In progress",
            url="https://github.com/acme/shop/issues/12",
        ),
        TrackerTicket(id="item-2", title="Draft card", status="No status", url=None),
    ]


@pytest.mark.asyncio
async def test_github_projects_rejects_invalid_external_ref() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(TrackerAdapterError, match="owner/project-number"):
            await GitHubProjectsTrackerAdapter(client).fetch_tickets(
                base_url="https://api.github.com",
                external_ref="not-a-project",
                token="secret",
            )


@pytest.mark.asyncio
async def test_jira_normalizes_issue_search_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/search/jql"
        assert request.headers["authorization"] == "Bearer secret"
        assert 'project = "PAY"' in request.url.params["jql"]
        return httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "PAY-42",
                        "fields": {
                            "summary": "Retry settlement",
                            "status": {"name": "To Do"},
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tickets = await JiraTrackerAdapter(client).fetch_tickets(
            base_url="https://acme.atlassian.net/",
            external_ref="PAY",
            token="secret",
        )

    assert tickets == [
        TrackerTicket(
            id="PAY-42",
            title="Retry settlement",
            status="To Do",
            url="https://acme.atlassian.net/browse/PAY-42",
        )
    ]


@pytest.mark.asyncio
async def test_azure_devops_queries_then_fetches_work_items() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers["authorization"].startswith("Basic ")
        if request.url.path.endswith("/_apis/wit/wiql"):
            return httpx.Response(200, json={"workItems": [{"id": 5}, {"id": 9}]})
        assert request.url.path.endswith("/_apis/wit/workitems")
        assert request.url.params["ids"] == "5,9"
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": 5,
                        "url": "https://dev.azure.com/acme/_apis/wit/workItems/5",
                        "fields": {"System.Title": "Ship API", "System.State": "Active"},
                    },
                    {
                        "id": 9,
                        "url": "https://dev.azure.com/acme/_apis/wit/workItems/9",
                        "fields": {"System.Title": "Write docs", "System.State": "New"},
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tickets = await AzureDevOpsTrackerAdapter(client).fetch_tickets(
            base_url="https://dev.azure.com/acme",
            external_ref="Payments",
            token="secret",
        )

    assert calls == ["/acme/Payments/_apis/wit/wiql", "/acme/Payments/_apis/wit/workitems"]
    assert [ticket.status for ticket in tickets] == ["Active", "New"]


@pytest.mark.asyncio
async def test_adapter_wraps_http_errors_without_exposing_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="secret rejected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TrackerAdapterError) as exc_info:
            await JiraTrackerAdapter(client).fetch_tickets(
                base_url="https://acme.atlassian.net",
                external_ref="PAY",
                token="secret",
            )

    assert "secret" not in str(exc_info.value)
