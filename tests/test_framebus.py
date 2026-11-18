import asyncio
import threading

from mvbridge.framebus import FrameBus, StoredFrame, Subscriber


def frame(seq: int) -> StoredFrame:
    return StoredFrame(f"payload-{seq}".encode(), b"jpeg", seq, 0, 1, 1)


def test_slow_client_only_gets_newest_frame():
    async def scenario():
        bus = FrameBus(["a"])
        subscriber = bus.subscribe("a", asyncio.get_running_loop())
        for seq in range(5):
            bus.publish("a", frame(seq))
        assert await subscriber.next() == b"payload-4"
        assert subscriber.replaced == 4

    asyncio.run(scenario())


def test_each_client_is_independent():
    async def scenario():
        bus = FrameBus(["a"])
        loop = asyncio.get_running_loop()
        first, second = bus.subscribe("a", loop), bus.subscribe("a", loop)
        bus.publish("a", frame(1))
        assert await first.next() == b"payload-1"
        bus.publish("a", frame(2))
        assert await first.next() == b"payload-2"
        assert await second.next() == b"payload-2"

    asyncio.run(scenario())


def test_feeds_are_isolated():
    async def scenario():
        bus = FrameBus(["a", "b"])
        subscriber = bus.subscribe("b", asyncio.get_running_loop())
        bus.publish("a", frame(1))
        await asyncio.sleep(0.01)
        bus.publish("b", frame(2))
        assert await subscriber.next() == b"payload-2"

    asyncio.run(scenario())


def test_new_client_never_receives_a_stale_frame():
    async def scenario():
        bus = FrameBus(["a"])
        bus.publish("a", frame(1))
        subscriber = bus.subscribe("a", asyncio.get_running_loop())
        try:
            await asyncio.wait_for(subscriber.next(), 0.05)
        except asyncio.TimeoutError:
            return True
        return False

    assert asyncio.run(scenario())


def test_latest_is_available_for_snapshots():
    bus = FrameBus(["a"])
    assert bus.latest("a") is None
    bus.publish("a", frame(3))
    assert bus.latest("a").seq == 3


def test_publish_from_another_thread_wakes_the_sender():
    async def scenario():
        bus = FrameBus(["a"])
        subscriber = bus.subscribe("a", asyncio.get_running_loop())
        threading.Timer(0.01, bus.publish, args=("a", frame(9))).start()
        return await asyncio.wait_for(subscriber.next(), 1)

    assert asyncio.run(scenario()) == b"payload-9"


def test_keys_do_not_replace_each_other():
    async def scenario():
        subscriber = Subscriber(asyncio.get_running_loop())
        subscriber.offer("m1", "meters")
        subscriber.offer("s1", "status")
        subscriber.offer("m2", "meters")
        return {await subscriber.next(), await subscriber.next()}

    assert asyncio.run(scenario()) == {"m2", "s1"}


def test_close_releases_a_waiting_sender():
    async def scenario():
        bus = FrameBus(["a"])
        subscriber = bus.subscribe("a", asyncio.get_running_loop())
        waiter = asyncio.create_task(subscriber.next())
        await asyncio.sleep(0)
        bus.unsubscribe("a", subscriber)
        return await asyncio.wait_for(waiter, 1)

    assert asyncio.run(scenario()) is None
