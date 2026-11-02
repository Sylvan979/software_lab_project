"""消息通知服务（对应组件图中的消息通知服务）。"""

from __future__ import annotations

from app.domain.models import Notification
from app.exceptions import PermissionDeniedError
from app.services.base import BaseService


class NotificationService(BaseService):
    def send(self, user_id: str, title: str, body: str) -> Notification:
        notification = Notification(
            notification_id=self.repos.db.next_id("NTF"),
            user_id=user_id,
            title=title,
            body=body,
        )
        self.repos.notifications.add(notification)
        return notification

    def send_many(self, user_ids: list[str], title: str, body: str) -> None:
        for user_id in dict.fromkeys(user_ids):
            self.send(user_id, title, body)

    def list_for(self, user_id: str, *, unread_only: bool = False) -> list[Notification]:
        items = self.repos.notifications.by_user(user_id)
        return [n for n in items if n.read is False] if unread_only else items

    def unread_count(self, user_id: str) -> int:
        return self.repos.notifications.unread_count(user_id)

    def mark_read(self, notification_id: str, user_id: str) -> Notification:
        notification = self.repos.notifications.get(notification_id)
        if notification.user_id != user_id:
            raise PermissionDeniedError("不能操作他人的消息")
        notification.read = True
        self.repos.notifications.update(notification)
        return notification

    def mark_all_read(self, user_id: str) -> int:
        count = 0
        for notification in self.repos.notifications.by_user(user_id):
            if not notification.read:
                notification.read = True
                self.repos.notifications.update(notification)
                count += 1
        return count

    def delete(self, notification_id: str, user_id: str) -> None:
        notification = self.repos.notifications.get(notification_id)
        if notification.user_id != user_id:
            raise PermissionDeniedError("不能操作他人的消息")
        self.repos.notifications.delete(notification_id)
