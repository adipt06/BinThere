import requests

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"


def get_resources(latitude, longitude, radius=2000):
    query = f"""
    [out:json] [timeout:600];

    (
    node["amenity"="waste_basket"]
    (around:{radius},{latitude},{longitude});

    nwr["amenity"="toilets"]
    (around:{radius},{latitude},{longitude});

    nwr["amenity"="recycling"]
    (around:{radius},{latitude},{longitude});

    );

    out center;

    """

    response = requests.post(OVERPASS_API_URL, data={"data": query}, timeout = 600)
    response.raise_for_status()
    data = response.json()
    resources = []

    for elements in data['elements']:
        osm_type = elements.get('type')
        osm_id = elements.get('id')

        center = elements.get('center', {})

        lat = elements.get('lat',center.get('lat'))
        lon = elements.get('lon',center.get('lon'))

        amenities = elements.get('tags', {}).get('amenity', 'Unknown')
        name = elements.get('tags', {}).get('name', 'Unknown')

        if lon is None or lat is None:
            continue

        if amenities == "waste_basket":
            amenities = "Trash Bin"

        elif amenities == "toilets":
            amenities = "Restroom"

        elif amenities == "recycling":
            amenities = "Recycling Center"

        

        resource = {"id": f"{osm_type}/{osm_id}", "name" : name, "type" : amenities, "latitude" : lat , "longitude" : lon}
        resources.append(resource)


    return resources

            

      
        
        
        
