"""Admin registration for the spaces hierarchy."""

from django.contrib import admin

from spaces.models import Building, Floor, Membership, Organisation, Room


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


class BuildingInline(admin.TabularInline):
    model = Building
    extra = 0
    fields = ["name", "address", "area_sqm", "occupancy"]
    show_change_link = True


class FloorInline(admin.TabularInline):
    model = Floor
    extra = 0
    fields = ["name", "level", "area_sqm", "occupancy"]
    show_change_link = True


class RoomInline(admin.TabularInline):
    model = Room
    extra = 0
    fields = ["name", "kind", "area_sqm", "occupancy"]
    show_change_link = True


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "building_count", "total_area_sqm", "total_occupancy"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [MembershipInline, BuildingInline]

    @admin.display(description="buildings")
    def building_count(self, obj) -> int:
        return obj.buildings.count()


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ["name", "organisation", "area_sqm", "total_area_sqm", "total_occupancy"]
    list_filter = ["organisation"]
    search_fields = ["name", "address"]
    inlines = [FloorInline]


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ["name", "building", "level", "area_sqm", "total_area_sqm"]
    list_filter = ["building__organisation", "building"]
    search_fields = ["name"]
    inlines = [RoomInline]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ["name", "floor", "kind", "area_sqm", "occupancy"]
    list_filter = ["kind", "floor__building__organisation"]
    search_fields = ["name"]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "organisation", "created_at"]
    list_filter = ["organisation"]
    search_fields = ["user__username", "organisation__name"]
    autocomplete_fields = ["user"]
