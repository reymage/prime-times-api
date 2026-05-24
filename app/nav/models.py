import enum

from tortoise import fields
from tortoise.models import Model


class NavArea(str, enum.Enum):
    main = "main"
    console = "console"


class NavItemType(str, enum.Enum):
    primary = "primary"
    category = "category"
    breaking = "breaking"


class NavMenu(Model):
    id = fields.IntField(pk=True)
    label = fields.CharField(max_length=100)
    slug = fields.CharField(max_length=120, unique=True)
    href = fields.CharField(max_length=255, null=True)
    area = fields.CharEnumField(NavArea, default=NavArea.main, max_length=20)
    item_type = fields.CharEnumField(NavItemType, default=NavItemType.primary, max_length=20)
    position = fields.IntField(default=0)
    is_active = fields.BooleanField(default=True)
    roles = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "nav_menus"
        ordering = ["area", "position"]
