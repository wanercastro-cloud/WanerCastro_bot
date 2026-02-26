from providers import fetch_candidates
from scoring import compute_score


async def build_candidates():
    raw = await fetch_candidates()
    out = []

    for c in raw:
        score, notes = compute_score(
            c["mcap"],
            c["vol24"],
            c["chg_1h"],
            c["chg_24h"],
            c.get("dex_boost", 0.0),
        )
        c["score"] = score
        c["notes"] = notes
        out.append(c)

    return sorted(out, key=lambda x: x["score"], reverse=True)