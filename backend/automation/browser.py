import webbrowser
import urllib.parse
from typing import Dict, Optional

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    requests = None  # type: ignore


def _get_logger():
    try:
        from backend.services import logger as project_logger  # type: ignore

        if hasattr(project_logger, "get_logger"):
            return project_logger.get_logger("automation.browser")
    except Exception:
        pass

    import logging

    lg = logging.getLogger("DeskmateAI.automation.browser")
    if not lg.handlers:
        lg.propagate = True
    return lg


LOGGER = _get_logger()


def _ok(message: str, result: Optional[dict] = None) -> Dict[str, object]:
    resp: Dict[str, object] = {"status": "success", "message": message}
    if result is not None:
        resp["result"] = result
    return resp


def _err(message: str) -> Dict[str, str]:
    return {"status": "error", "message": message}


def open_url(url: str) -> Dict[str, object]:
    try:
        if not url:
            return _err("URL is required")
        webbrowser.open(url, new=2)
        LOGGER.info("Opened URL: %s", url)
        return _ok("URL opened", result={"url": url})
    except Exception as error:
        LOGGER.exception("Failed to open URL: %s", url)
        return _err(str(error))


def search_google(query: str) -> Dict[str, object]:
    try:
        if not query:
            return _err("Query is required")
        q = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={q}"
        webbrowser.open(url, new=2)
        LOGGER.info("Opened Google search for: %s", query)
        return _ok("Search opened", result={"query": query, "url": url})
    except Exception as error:
        LOGGER.exception("Failed Google search for: %s", query)
        return _err(str(error))


def get_wikipedia_summary(query: str) -> Dict[str, object]:
    try:
        if not query:
            return _err("Query is required")
        if requests is None:
            return _err("requests not available")
        title = urllib.parse.quote(query.strip().replace(" ", "_"))
        api_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
        headers = {"Accept": "application/json", "User-Agent": "DeskmateAI/1.0"}
        resp = requests.get(api_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            summary = data.get("extract") or data.get("description") or ""
            page_url = data.get("content_urls", {}).get("desktop", {}).get("page")
            LOGGER.info("Fetched Wikipedia summary for: %s", query)
            return _ok(
                "Wikipedia summary fetched",
                result={"summary": summary, "url": page_url, "raw": data},
            )
        elif resp.status_code == 404:
            return _err("Wikipedia page not found")
        else:
            return _err(f"Wikipedia API error: {resp.status_code}")
    except Exception as error:
        LOGGER.exception("Failed to fetch Wikipedia summary for: %s", query)
        return _err(str(error))


