# Probe: run_missed_checkout_digest message content per manager scope (push mocked, fake subs removed after)
import asyncio
import sys
import uuid

sys.path.insert(0, "/app/backend")
import server  # noqa: E402

sent = []


async def fake_push(subs, payload):
    sent.append((subs[0]["user_id"] if subs else None, payload))
    return len(subs)


async def main():
    server.push_to_subscriptions = fake_push
    db = server.db
    day_key, yday = "2099-01-02", "2099-01-01"
    tag = uuid.uuid4().hex[:6]
    subs = [{"user_id": u, "endpoint": f"https://TEST_{tag}/{u}", "reminders": True, "keys": {}} for u in ("user_testadmin01", "user_testsub01")]
    await db.push_subscriptions.insert_many([dict(s) for s in subs])
    recs = [
        {"record_id": f"TEST_att_{tag}_1", "user_id": "user_testemp01", "date": yday, "check_out": None},
        {"record_id": f"TEST_att_{tag}_2", "user_id": "user_testemp02", "date": yday, "check_out": "x", "auto_closed": True, "auto_close_reason": "missed checkout"},
    ]
    await db.attendance.insert_many([dict(r) for r in recs])
    try:
        await server.run_missed_checkout_digest(day_key)
        for uid, p in sent:
            print(uid, "|", p["title"], "|", p["body"])
        sent.clear()
        await db.attendance.delete_many({"record_id": {"$in": [r["record_id"] for r in recs]}})
        await server.run_missed_checkout_digest(day_key)
        for uid, p in sent:
            print("EMPTY", uid, "|", p["title"], "|", p["body"])
    finally:
        await db.attendance.delete_many({"record_id": {"$in": [r["record_id"] for r in recs]}})
        await db.push_subscriptions.delete_many({"endpoint": {"$regex": f"^https://TEST_{tag}/"}})


asyncio.run(main())
