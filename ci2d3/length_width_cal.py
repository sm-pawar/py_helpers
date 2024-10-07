import numpy as np
import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import snap
from itertools import combinations

shapefile_path = 'D:/UNI_Stir/Projects/CI2D3/InProgress/python/3020_formatted.shp'

gdf = gpd.read_file(shapefile_path)
#polygon = gdf.geometry[0]

def get_width_length(polygon):
    # Length calculation
    # Step 1: Create a minimum rotated bounding box
    min_rotated_rect = polygon.minimum_rotated_rectangle

    # Step 1.5: Snap the polygon to the bounding box
    snap_poly = snap(min_rotated_rect, polygon, 0.5)

    # Step 2: Find the points where the polygon touches the snap bounding box
    min_rotated_rect_coords = list(snap_poly.exterior.coords)
    touching_points = []
    for i in range(len(min_rotated_rect_coords) - 1):
        edge = LineString([min_rotated_rect_coords[i], min_rotated_rect_coords[i + 1]])
        intersection = polygon.intersection(edge)
        if not intersection.is_empty:
            if isinstance(intersection, Point):
                touching_points.append(intersection)
            elif isinstance(intersection, LineString):
                touching_points.extend([Point(coord) for coord in intersection.coords])

    # Step 3: Calculate length
    max_length = 0
    length_line = None
    for p1, p2 in combinations(touching_points, 2):
        distance = p1.distance(p2)
        if distance > max_length:
            max_length = distance
            length_line = LineString([p1, p2])


    # Calculate width
    max_width = 0
    width_line = None
    width_inter = []
    for point in touching_points:
        
        # Step 1: Find the closest point on the line to the given point
        closest_point = length_line.interpolate(length_line.project(point))

        # Step 2: Create a perpendicular line from the point to the closest point on the line
        perpendicular_line = LineString([point, closest_point])
        #perpendicular_lines.append(perpendicular_line)


        # Step 3: Calculate the direction vector of the line
        x1, y1 = perpendicular_line.coords[0]
        x2, y2 = perpendicular_line.coords[1]
        direction_vector = (x2 - x1, y2 - y1)

        # Step 4: Extend the line in both directions
        scale_factor = 1000  # Arbitrary large number to extend the line in both directions

        # Extend the line forward from the second point
        new_point_forward = (x2 + scale_factor * direction_vector[0], y2 + scale_factor * direction_vector[1])

        # Extend the line backward from the first point (using negative direction)
        new_point_backward = (x1 - scale_factor * direction_vector[0], y1 - scale_factor * direction_vector[1])

        # Create the extended line (ray in both directions)
        extended_line = LineString([new_point_backward, new_point_forward])

        # Step 5: Find the intersection of the extended line with the polygon
        intersection_line = extended_line.intersection(polygon)

        width_inter.append(intersection_line)

        if isinstance(intersection_line, LineString):
            width = intersection_line.length
            if width > max_width:
                max_width = width
                width_line = intersection_line

    return max_length, max_width

# Test the function
gdf['width'] = np.nan
gdf['length'] = np.nan

# Apply the function to each row of the GeoDataFrame
gdf['length'], gdf['width'] = zip(*gdf.geometry.apply(get_width_length))

print(gdf[['length', 'width']])