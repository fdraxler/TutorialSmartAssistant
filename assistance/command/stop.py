from assistance.command import Command


class StopCommand(Command):
    def __init__(self, printer, function):
        super().__init__(printer, "stop", ("exit", "finish", "cancel", "terminate"), 0, 0)
        self._function = function

    def __call__(self):
        self._function()
