from monpy.oo.binding import bind_session
from monpy.oo.session import Session


def test_bind_session_decorator_sets_session():
    class FakeClient:
        pass

    sess = Session(FakeClient())

    @bind_session(sess)
    class Example:
        def __init__(self, id: str):
            self.id = id

    e = Example("1")
    assert getattr(e, "_session", None) is sess


