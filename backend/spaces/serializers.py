"""Serializers for the spaces hierarchy.

Every serializer exposes the resolved `total_area_sqm` / `total_occupancy`
alongside the stored values, so a client can tell a stated area from a derived
one without a second request.
"""

from rest_framework import serializers

from spaces.models import Building, Floor, Membership, Organisation, Room


class _SpaceNodeSerializer(serializers.ModelSerializer):
    """Shared read-only derived fields for Building, Floor and Room."""

    total_area_sqm = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    total_occupancy = serializers.IntegerField(read_only=True)


class RoomSerializer(_SpaceNodeSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    organisation_id = serializers.PrimaryKeyRelatedField(
        source="organisation", read_only=True
    )

    class Meta:
        model = Room
        fields = [
            "id",
            "floor",
            "organisation_id",
            "name",
            "kind",
            "kind_display",
            "area_sqm",
            "occupancy",
            "total_area_sqm",
            "total_occupancy",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class FloorSerializer(_SpaceNodeSerializer):
    room_count = serializers.IntegerField(source="rooms.count", read_only=True)

    class Meta:
        model = Floor
        fields = [
            "id",
            "building",
            "name",
            "level",
            "area_sqm",
            "occupancy",
            "total_area_sqm",
            "total_occupancy",
            "room_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class BuildingSerializer(_SpaceNodeSerializer):
    floor_count = serializers.IntegerField(source="floors.count", read_only=True)

    class Meta:
        model = Building
        fields = [
            "id",
            "organisation",
            "name",
            "address",
            "latitude",
            "longitude",
            "area_sqm",
            "occupancy",
            "total_area_sqm",
            "total_occupancy",
            "floor_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class OrganisationSerializer(serializers.ModelSerializer):
    total_area_sqm = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    total_occupancy = serializers.IntegerField(read_only=True)
    building_count = serializers.IntegerField(source="buildings.count", read_only=True)
    member_count = serializers.IntegerField(source="members.count", read_only=True)

    class Meta:
        model = Organisation
        fields = [
            "id",
            "name",
            "slug",
            "total_area_sqm",
            "total_occupancy",
            "building_count",
            "member_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["slug", "created_at", "updated_at"]


class MembershipSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    role = serializers.CharField(source="user.role", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "username", "role", "organisation", "created_at"]
        read_only_fields = ["created_at"]


# --- Nested tree ---------------------------------------------------------------


class TreeRoomSerializer(RoomSerializer):
    class Meta(RoomSerializer.Meta):
        fields = ["id", "name", "kind", "kind_display", "area_sqm", "occupancy"]


class TreeFloorSerializer(serializers.ModelSerializer):
    rooms = TreeRoomSerializer(many=True, read_only=True)
    total_area_sqm = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    total_occupancy = serializers.IntegerField(read_only=True)

    class Meta:
        model = Floor
        fields = ["id", "name", "level", "total_area_sqm", "total_occupancy", "rooms"]


class TreeBuildingSerializer(serializers.ModelSerializer):
    floors = TreeFloorSerializer(many=True, read_only=True)
    total_area_sqm = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    total_occupancy = serializers.IntegerField(read_only=True)

    class Meta:
        model = Building
        fields = [
            "id",
            "name",
            "address",
            "latitude",
            "longitude",
            "total_area_sqm",
            "total_occupancy",
            "floors",
        ]


class TreeOrganisationSerializer(serializers.ModelSerializer):
    """
    Whole hierarchy in one response, for the Phase 18 spaces tree.

    Saves the frontend four round trips and a client-side join.
    """

    buildings = TreeBuildingSerializer(many=True, read_only=True)
    total_area_sqm = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    total_occupancy = serializers.IntegerField(read_only=True)

    class Meta:
        model = Organisation
        fields = [
            "id",
            "name",
            "slug",
            "total_area_sqm",
            "total_occupancy",
            "buildings",
        ]
