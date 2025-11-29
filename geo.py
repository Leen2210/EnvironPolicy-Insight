from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

# 1. Initialize the geolocator
# You need to provide a unique user_agent string to identify your application.
geolocator = Nominatim(user_agent="my_geopy_test_app")

# 2. Define the address to geocode
address = "Kecamatan Gubeng"

# 3. Perform the geocoding
try:
    location = geolocator.geocode(address)

    # 4. Process the results
    if location:
        print(f"Address: {location.address}")
        print(f"Latitude: {location.latitude}")
        print(f"Longitude: {location.longitude}")
    else:
        print(f"Could not find location for: {address}")

except GeocoderTimedOut:
    print("Geocoding service timed out. Please try again later.")
except GeocoderServiceError as e:
    print(f"Geocoding service error: {e}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")