import json
from types import SimpleNamespace


class FakeActivityDB:
    def __init__(self, pending_ids):
        self.pending_ids = list(pending_ids)
        self.saved = []
        self.synced = []
        self.exceptions = []

    def saveActivity(self, activity_id, source, target):
        self.saved.append((activity_id, source, target))

    def getUnSyncActivity(self, source, target):
        return list(self.pending_ids)

    def updateSyncStatus(self, activity_id, source, target):
        self.synced.append((activity_id, source, target))

    def updateExceptionSyncStatus(self, activity_id, source, target):
        self.exceptions.append((activity_id, source, target))


def garmin_business_response(code, content, status_code=400):
    return SimpleNamespace(
        status_code=status_code,
        text=json.dumps(
            {
                "detailedImportResult": {
                    "failures": [{"messages": [{"code": code, "content": content}]}]
                }
            }
        ),
    )
