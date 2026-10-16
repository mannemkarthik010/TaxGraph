"""Shared setup for the filing modules: an isolated database per module (filing and freezing lock the
workpaper, so they must not touch the shared test database), and helpers that bring the workpaper to a
state the partner can approve — through the public API, acting as the right people."""


from tests.conftest import as_user, isolated_client  # noqa: F401  (re-exported for the filing modules)

PREPARER, REVIEWER, PARTNER, QR, CLIENT = "st-01", "st-02", "st-03", "st-06", "cu-01"
MILEAGE, CARD = "dup-page:D23#p3:SchC.44a", "card-in-books:D21:SchC.1"


def post(c, user, path, body=None):
    return c.post(path, headers=as_user(user), json=body or {})


def get(c, user, path):
    return c.get(path, headers=as_user(user))


def state(c, user=PREPARER):
    return get(c, user, "/api/filing/state").json()


def act(c, user, action, **body):
    return post(c, user, f"/api/filing/actions/{action}", body)


def replay(c, user=PREPARER):
    return post(c, user, "/api/filing/replay")


def sign_everything(c):
    for a in get(c, PREPARER, "/api/signoffs").json()["areas"]:
        for user, lvl in ((PREPARER, "prepared"), (REVIEWER, "reviewed"), (PARTNER, "partner")):
            cur = next(x for x in next(y for y in get(c, PREPARER, "/api/signoffs").json()["areas"] if y["key"] == a["key"])["levels"]
                       if x["level"] == lvl)
            if cur["status"] != "signed":
                r = post(c, user, "/api/signoffs", {"area_key": a["key"], "level": lvl})
                assert r.status_code == 201, (a["key"], lvl, r.json())


def decide_everything(c):
    for g in get(c, PARTNER, "/api/inbox").json()["groups"]:
        for it in g["items"]:
            if it["source"] == "adjustment":
                assert post(c, PARTNER, f"/api/adjustments/{it['detail']['adjustment_id']}/approve").status_code == 200
            elif it["source"] == "judgment":
                for u in (REVIEWER, PARTNER):
                    post(c, u, f"/api/judgments/{it['detail']['judgment_id']}/review", {})
            elif it["source"] == "question":
                post(c, PARTNER, f"/api/client-questions/{it['detail']['question_id']}/withdraw", {"note": "not needed"})
            else:
                assert post(c, PARTNER, f"/api/inbox/{'resolve' if it['source'] == 'note' else 'accept'}",
                            {"key": it["key"], "note": "Dispositioned before partner approval."}).status_code == 200


