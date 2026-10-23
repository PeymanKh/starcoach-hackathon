from rest_framework import serializers

from apps.agents.llm import DEFAULT_MODEL, DEFAULT_THINKING, MODELS, THINKING_LEVELS
from apps.agents.models import Conversation


class RunCreateSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000)
    thread_id = serializers.RegexField(r"^[A-Za-z0-9_-]{1,64}$", required=False)
    model = serializers.ChoiceField(choices=list(MODELS), default=DEFAULT_MODEL)
    thinking = serializers.ChoiceField(choices=THINKING_LEVELS, default=DEFAULT_THINKING)
    lat = serializers.FloatField(min_value=-90, max_value=90, required=False)
    lon = serializers.FloatField(min_value=-180, max_value=180, required=False)

    def validate(self, attrs):
        if ("lat" in attrs) != ("lon" in attrs):
            raise serializers.ValidationError("Send both lat and lon, or neither.")
        return attrs


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["thread_id", "title", "created_at", "updated_at"]
