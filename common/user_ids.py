from rest_framework import serializers


class UserIdField(serializers.Field):
    default_error_messages = {
        "invalid": "Provide a non-empty user ID as a string or integer."
    }

    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (str, int)):
            self.fail("invalid")
        value = str(data).strip()
        if not value or len(value) > 255:
            self.fail("invalid")
        return value

    def to_representation(self, value):
        return str(value)
