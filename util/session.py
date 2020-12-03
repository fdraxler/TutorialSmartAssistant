class BaseSession:
    def __init__(self):
        self._session = None

    def get_online_state(self):
        raise NotImplementedError()

    @property
    def online(self):
        return self.get_online_state() == 'online'

    def login(self):
        raise NotImplementedError()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logout()

    def logout(self):
        raise NotImplementedError()
