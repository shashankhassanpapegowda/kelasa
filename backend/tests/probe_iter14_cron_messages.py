# In-process probe: verifies morning-cron titles/bodies and celebrations=false skip (patches push sender)
import asyncio, sys
sys.path.insert(0, "/app/backend")
import server

captured = []

async def fake_push(subs, payload):
    for s in subs:
        captured.append((s["user_id"], s["endpoint"], payload["title"], payload["body"]))
    return len(subs)

async def main():
    server.push_to_subscriptions = fake_push
    db = server.db
    eps = [("user_testemp01", "https://x/TEST_p_ravi", None), ("user_testadmin01", "https://x/TEST_p_admin", None),
           ("user_testemp02", "https://x/TEST_p_anita_off", False)]
    for uid, ep, cel in eps:
        doc = {"endpoint": ep, "user_id": uid, "keys": {"p256dh": "x", "auth": "y"}}
        if cel is not None:
            doc["celebrations"] = cel
        await db.push_subscriptions.insert_one(doc)
    key = "2099-01-01"
    try:
        day = server.datetime.now(server.ZoneInfo(server.DEFAULT_TZ)).date().isoformat()
        await db.cron_runs.delete_many({"key": f"celebrations-{day}"})
        await db.cron_runs.insert_one({"key": f"celebrations-{day}", "status": "queued"})
        await server.run_morning_celebrations(day)
        run = await db.cron_runs.find_one({"key": f"celebrations-{day}"}, {"_id": 0})
        print("RUN", run)
        for c in captured:
            print("PUSH", c)
        assert not any(c[0] == "user_testemp02" for c in captured), "celebrations=false not skipped"
    finally:
        await db.push_subscriptions.delete_many({"endpoint": {"$regex": "TEST_p_"}})

asyncio.run(main())
