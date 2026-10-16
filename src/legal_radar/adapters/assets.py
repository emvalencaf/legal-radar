"""Static files shipped inside the package, read through `importlib.resources`."""

from importlib.resources import files


def cytoscape_js() -> str:
    """Cytoscape.js (MIT), embedded in the graph page so it works offline."""
    return (files("legal_radar.adapters") / "static" / "cytoscape.min.js").read_text("utf-8")
