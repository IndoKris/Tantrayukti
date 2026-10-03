"""Satellite routes, mounted under /api/ by config.urls."""

from django.urls import path

from satellite.views import (
    CityNo2ListView,
    CommunityMapView,
    Co2TrendView,
    SatelliteHotspotsView,
)

app_name = "satellite"

urlpatterns = [
    # Flat path: named explicitly in the project plan.
    path("satellite-hotspots/", SatelliteHotspotsView.as_view(), name="hotspots"),
    path("satellite/cities/", CityNo2ListView.as_view(), name="cities"),
    path("community/map/", CommunityMapView.as_view(), name="community-map"),
    path("community/co2-trend/", Co2TrendView.as_view(), name="co2-trend"),
]
