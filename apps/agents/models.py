from django.db import models

TITLE_LENGTH = 80


class Conversation(models.Model):
    """
    One chat with the agent, for the sidebar list.

    The messages themselves live in the LangGraph checkpointer,
    stored under the same thread_id.
    """

    thread_id = models.CharField(primary_key=True, max_length=64)
    title = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title

    @classmethod
    def record_message(cls, thread_id: str, message: str) -> "Conversation":
        """New chat: create it, titled by its first message. Existing chat: move it to the top."""
        conversation, created = cls.objects.get_or_create(
            thread_id=thread_id, defaults={"title": message[:TITLE_LENGTH]}
        )
        if not created:
            conversation.save(update_fields=["updated_at"])
        return conversation
