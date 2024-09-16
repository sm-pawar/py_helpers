import rasterio
import numpy as np

# Define the pixel size (25 meters in both x and y directions)
pixel_size = 25  # meters

def calculate_area_per_category(tiff_file):
    # Open the TIFF file
    with rasterio.open(tiff_file) as src:
        # Read the data as a numpy array
        data = src.read(1)  # assuming single band; for multiband, adjust accordingly

        # Get unique categories and their counts
        unique, counts = np.unique(data, return_counts=True)

        # Calculate the area for each category
        pixel_area = pixel_size * pixel_size  # Area of each pixel in square meters
        areas = counts * pixel_area  # Total area per category

        # Create a dictionary to store the category and area information
        category_area = dict(zip(unique, areas))

        # Print the results
        print("Category -> Number of Pixels -> Area (square meters)")
        for category, count, area in zip(unique, counts, areas):
            print(f"{category} -> {count} pixels -> {area:.2f} square meters")

    return category_area

# Example usage
tiff_file = 'your_tiff_file.tif'  # Replace with the path to your TIFF file
category_areas = calculate_area_per_category(tiff_file)
