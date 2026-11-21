import httpx
from test_flow import RACCOON, add_image, animal, classify, detect

from observatory_edge.species_info import (fetch_species_info, get_species_info,
                                           refresh_species_info, wiki_candidates)

SQUIRRELS = "abc;mammalia;rodentia;sciuridae;;;squirrel family"


def seed(conn, settings, tmp_path, label=RACCOON):
    m = add_image(conn, settings, tmp_path, live=False)
    detect(conn, settings, m, [animal()])
    classify(conn, settings, m, label)


def wiki_transport(pages: dict, calls: list):
    def handler(req: httpx.Request):
        calls.append(str(req.url))
        if req.url.host == "upload.wikimedia.org":
            return httpx.Response(200, content=b"\xff\xd8jpegbytes", headers={"content-type": "image/jpeg"})
        title = req.url.path.rsplit("/", 1)[-1]
        if title in pages:
            return httpx.Response(200, json=pages[title])
        return httpx.Response(404, json={"type": "not_found"})
    return httpx.MockTransport(handler)


def page(title):
    return {"type": "standard", "title": title, "extract": f"The {title} is an animal.",
            "thumbnail": {"source": "https://upload.wikimedia.org/x.jpg"},
            "content_urls": {"desktop": {"page": f"https://en.wikipedia.org/wiki/{title}"}}}


def test_candidates_prefer_binomial(conn, settings, tmp_path):
    seed(conn, settings, tmp_path)
    assert wiki_candidates(conn, "northern raccoon")[0] == "Procyon lotor"


def test_rolled_up_label_uses_family(conn, settings, tmp_path):
    seed(conn, settings, tmp_path, SQUIRRELS)
    assert wiki_candidates(conn, "squirrel family")[0] == "Sciuridae"


def test_fetch_stores_extract_and_thumbnail(conn, settings, tmp_path):
    seed(conn, settings, tmp_path)
    calls = []
    client = httpx.Client(transport=wiki_transport({"Procyon_lotor": page("Raccoon")}, calls))
    assert fetch_species_info(conn, settings, "northern raccoon", client) == "ok"
    info = get_species_info(conn, settings, "northern raccoon")
    assert info["extract"].startswith("The Raccoon") and info["has_image"]
    assert info["scientific_name"] == "procyon lotor"
    assert info["facts"]["activity"] == "nocturnal"
    assert all("lat" not in c and "lon" not in c for c in calls)  # only names leave the Pi


def test_404_falls_back_to_common_name(conn, settings, tmp_path):
    seed(conn, settings, tmp_path)
    client = httpx.Client(transport=wiki_transport({"Northern_raccoon": page("Raccoon")}, []))
    assert fetch_species_info(conn, settings, "northern raccoon", client) == "ok"


def test_network_error_records_error_without_content(conn, settings, tmp_path):
    seed(conn, settings, tmp_path)

    def boom(req):
        raise httpx.ConnectError("offline")
    client = httpx.Client(transport=httpx.MockTransport(boom))
    assert refresh_species_info(conn, settings, client) == 0
    info = get_species_info(conn, settings, "northern raccoon")
    assert info["status"] == "error" and not info.get("extract")


def test_refresh_skips_fresh_entries(conn, settings, tmp_path):
    seed(conn, settings, tmp_path)
    calls = []
    client = httpx.Client(transport=wiki_transport({"Procyon_lotor": page("Raccoon")}, calls))
    assert refresh_species_info(conn, settings, client) == 1
    n = len(calls)
    assert refresh_species_info(conn, settings, client) == 0 and len(calls) == n
