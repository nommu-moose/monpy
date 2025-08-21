from monpy.oo.base import BaseModel
from monpy.oo.binding import bind_session
from monpy.oo.session import Session


def test_basemodel_edit_context_and_save():
    calls = {"flushed": 0}

    class Dummy(BaseModel):
        def _flush_changes(self) -> None:
            calls["flushed"] += 1

    class FakeClient:
        pass

    sess = Session(FakeClient())
    d = Dummy(id="1").bind(sess)
    # save with no dirty does nothing
    d.save()
    assert calls["flushed"] == 0
    # edit context triggers save on exit
    with d.edit() as ed:
        ed.mark_dirty("x", 1)
    assert calls["flushed"] == 1
    # refresh calls _refresh_from_api (no-op default) without error
    d.refresh()


def test_bind_session_exception_path():
    class BlockSessionSet:
        def __init__(self):
            self.id = "1"

        def __setattr__(self, name, value):
            if name == "_session":
                raise RuntimeError("blocked")
            super().__setattr__(name, value)

    class FakeClient:
        pass

    sess = Session(FakeClient())

    @bind_session(sess)
    class Example(BlockSessionSet):
        pass

    # should not raise in decorator despite blocked _session assignment
    _ = Example()


