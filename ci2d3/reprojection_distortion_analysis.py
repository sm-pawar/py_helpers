import geopandas as gpd
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from shapely.geometry import LineString, Point
import math
from pyproj import CRS, Transformer

def calculate_distortion_metrics(shapefile_path, source_crs=None, target_crs="EPSG:5937"):
    """
    Calculate distortion metrics when reprojecting geometries from source CRS to target CRS.
    
    Parameters:
    -----------
    shapefile_path : str
        Path to the input shapefile
    source_crs : str, optional
        Source CRS (if None, will use the CRS defined in the shapefile)
    target_crs : str
        Target CRS for reprojection analysis
        
    Returns:
    --------
    GeoDataFrame with original geometries and distortion metrics
    """
    # Read the shapefile
    print(f"Reading shapefile: {shapefile_path}")
    gdf = gpd.read_file(shapefile_path)
    
    # If source_crs is provided, set it explicitly
    if source_crs:
        gdf.crs = source_crs
    
    # Store the original CRS for reference
    original_crs = gdf.crs
    print(f"Original CRS: {original_crs}")
    print(f"Target CRS: {target_crs}")
    
    # Create a copy of the GeoDataFrame with reprojected geometries
    gdf_reprojected = gdf.to_crs(target_crs)
    
    # Create transformer objects for direct coordinate transformation
    transformer = Transformer.from_crs(original_crs, target_crs, always_xy=True)
    
    # Initialize lists to store results
    results = []
    
    # Process each geometry in the shapefile
    for idx, geom in enumerate(gdf.geometry):
        if geom.is_empty:
            continue
            
        # Extract coordinates based on geometry type
        if geom.geom_type == 'Polygon' or geom.geom_type == 'MultiPolygon':
            # For polygons, extract exterior and interior rings
            coords_list = []
            
            if geom.geom_type == 'Polygon':
                coords_list.append(list(geom.exterior.coords))
                for interior in geom.interiors:
                    coords_list.append(list(interior.coords))
            else:  # MultiPolygon
                for polygon in geom.geoms:
                    coords_list.append(list(polygon.exterior.coords))
                    for interior in polygon.interiors:
                        coords_list.append(list(interior.coords))
        
        elif geom.geom_type == 'LineString' or geom.geom_type == 'MultiLineString':
            # For lines, extract all vertices
            coords_list = []
            
            if geom.geom_type == 'LineString':
                coords_list.append(list(geom.coords))
            else:  # MultiLineString
                for line in geom.geoms:
                    coords_list.append(list(line.coords))
        
        elif geom.geom_type == 'Point' or geom.geom_type == 'MultiPoint':
            # Skip points as we need at least line segments to calculate distortion
            continue
        
        # Process each coordinate sequence
        for coords in coords_list:
            # Skip if not enough points
            if len(coords) < 2:
                continue
                
            # Calculate metrics for each segment
            for i in range(len(coords) - 1):
                p1 = coords[i]
                p2 = coords[i + 1]
                
                # Calculate distance in original projection
                orig_dist = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                
                # Transform points to target projection using transformer
                p1_transformed = transformer.transform(p1[0], p1[1])
                p2_transformed = transformer.transform(p2[0], p2[1])
                
                # Calculate distance in target projection
                repr_dist = math.sqrt((p2_transformed[0] - p1_transformed[0])**2 + 
                                      (p2_transformed[1] - p1_transformed[1])**2)
                
                # Calculate scale factor (how much the distance changed)
                if orig_dist > 0:
                    scale_factor = repr_dist / orig_dist
                else:
                    scale_factor = np.nan
                
                # Calculate angle in original projection
                orig_angle = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
                
                # Calculate angle in reprojected coordinates
                repr_angle = math.degrees(math.atan2(p2_transformed[1] - p1_transformed[1], 
                                                    p2_transformed[0] - p1_transformed[0]))
                
                # Calculate angle difference (rotation)
                angle_diff = (repr_angle - orig_angle + 180) % 360 - 180
                
                # Create a midpoint for this segment (for visualization)
                midpoint_x = (p1[0] + p2[0]) / 2
                midpoint_y = (p1[1] + p2[1]) / 2
                
                # Store results
                results.append({
                    'geometry_id': idx,
                    'segment_id': i,
                    'orig_x1': p1[0],
                    'orig_y1': p1[1],
                    'orig_x2': p2[0],
                    'orig_y2': p2[1],
                    'repr_x1': p1_transformed[0],
                    'repr_y1': p1_transformed[1],
                    'repr_x2': p2_transformed[0],
                    'repr_y2': p2_transformed[1],
                    'orig_dist': orig_dist,
                    'repr_dist': repr_dist,
                    'scale_factor': scale_factor,
                    'orig_angle': orig_angle,
                    'repr_angle': repr_angle,
                    'angle_diff': angle_diff,
                    'midpoint_x': midpoint_x,
                    'midpoint_y': midpoint_y
                })
    
    # Create a DataFrame from results
    if not results:
        print("No valid segments found for analysis")
        return None
    
    df_results = pd.DataFrame(results)
    
    # Create a GeoDataFrame with midpoints for visualization
    geometry = [Point(xy) for xy in zip(df_results['midpoint_x'], df_results['midpoint_y'])]
    distortion_gdf = gpd.GeoDataFrame(df_results, geometry=geometry, crs=original_crs)
    
    # Calculate summary statistics
    summary_stats = {
        'mean_scale_factor': df_results['scale_factor'].mean(),
        'median_scale_factor': df_results['scale_factor'].median(),
        'min_scale_factor': df_results['scale_factor'].min(),
        'max_scale_factor': df_results['scale_factor'].max(),
        'std_scale_factor': df_results['scale_factor'].std(),
        'mean_angle_diff': df_results['angle_diff'].mean(),
        'median_angle_diff': df_results['angle_diff'].median(),
        'min_angle_diff': df_results['angle_diff'].min(),
        'max_angle_diff': df_results['angle_diff'].max(),
        'std_angle_diff': df_results['angle_diff'].std()
    }
    
    print("\nDistortion Summary Statistics:")
    for key, value in summary_stats.items():
        print(f"{key}: {value}")
    
    # Calculate polygon-level statistics
    if 'geometry_id' in df_results:
        polygon_stats = df_results.groupby('geometry_id').agg({
            'scale_factor': ['mean', 'median', 'min', 'max', 'std'],
            'angle_diff': ['mean', 'median', 'min', 'max', 'std']
        })
        
        # Add polygon-level statistics back to the original geodataframe
        for stat in ['mean', 'median', 'min', 'max', 'std']:
            gdf[f'scale_factor_{stat}'] = [
                polygon_stats.loc[i, ('scale_factor', stat)] if i in polygon_stats.index else np.nan
                for i in range(len(gdf))
            ]
            gdf[f'angle_diff_{stat}'] = [
                polygon_stats.loc[i, ('angle_diff', stat)] if i in polygon_stats.index else np.nan
                for i in range(len(gdf))
            ]
    
    # Calculate areas before and after reprojection for polygons
    if any(gdf.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])):
        # Original areas
        gdf['orig_area'] = gdf.geometry.area
        
        # Get reprojected areas
        gdf['repr_area'] = gdf_reprojected.geometry.area
        
        # Calculate area scale factor
        gdf['area_scale'] = gdf['repr_area'] / gdf['orig_area']
        
        print("\nArea Change Statistics:")
        print(f"Mean area scale factor: {gdf['area_scale'].mean()}")
        print(f"Min area scale factor: {gdf['area_scale'].min()}")
        print(f"Max area scale factor: {gdf['area_scale'].max()}")
    
    return gdf, distortion_gdf, summary_stats

def visualize_distortions(gdf, distortion_gdf, output_path=None):
    """
    Create visualizations of the distortion metrics
    
    Parameters:
    -----------
    gdf : GeoDataFrame
        Original geodataframe with distortion metrics
    distortion_gdf : GeoDataFrame
        GeoDataFrame with segment-level distortion metrics
    output_path : str, optional
        Path to save the output visualizations
    """
    # Create figure with multiple subplots
    fig, axs = plt.subplots(2, 2, figsize=(20, 16))
    
    # Plot 1: Scale factor (stretching/compression)
    distortion_gdf.plot(column='scale_factor', ax=axs[0, 0], 
                        cmap='coolwarm', legend=True,
                        vmin=0.9, vmax=1.1)
    axs[0, 0].set_title('Scale Factor (Distance Distortion)')
    
    # Plot 2: Angle difference (rotation/shearing)
    distortion_gdf.plot(column='angle_diff', ax=axs[0, 1], 
                       cmap='coolwarm', legend=True,
                       vmin=-5, vmax=5)
    axs[0, 1].set_title('Angle Difference (Rotation Distortion)')
    
    # Plot 3: Original geometries
    if 'orig_area' in gdf.columns:
        gdf.plot(column='area_scale', ax=axs[1, 0], 
                cmap='coolwarm', legend=True,
                vmin=0.9, vmax=1.1)
        axs[1, 0].set_title('Area Scale Factor by Polygon')
    else:
        gdf.plot(ax=axs[1, 0])
        axs[1, 0].set_title('Original Geometries')
    
    # Plot 4: Histogram of scale factors
    axs[1, 1].hist(distortion_gdf['scale_factor'], bins=50, alpha=0.7)
    axs[1, 1].set_title('Distribution of Scale Factors')
    axs[1, 1].set_xlabel('Scale Factor')
    axs[1, 1].set_ylabel('Frequency')
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path)
        print(f"Saved visualization to {output_path}")
    else:
        plt.show()

def main(shapefile_path, source_crs=None, target_crs="EPSG:5937", output_prefix=None):
    """
    Main function to run the distortion analysis workflow
    
    Parameters:
    -----------
    shapefile_path : str
        Path to the input shapefile
    source_crs : str, optional
        Source CRS (if None, will use the CRS defined in the shapefile)
    target_crs : str
        Target CRS for reprojection analysis
    output_prefix : str, optional
        Prefix for output files
    """
    # Set output prefix if not provided
    if output_prefix is None:
        output_prefix = "distortion_analysis"
    
    # Calculate distortion metrics
    gdf, distortion_gdf, summary_stats = calculate_distortion_metrics(
        shapefile_path, source_crs, target_crs
    )
    
    # Save results
    gdf.to_file(f"{output_prefix}_polygons.shp")
    distortion_gdf.to_file(f"{output_prefix}_segments.shp")
    
    # Save summary stats to CSV
    pd.DataFrame([summary_stats]).to_csv(f"{output_prefix}_summary.csv", index=False)
    
    # Create visualizations
    visualize_distortions(gdf, distortion_gdf, f"{output_prefix}_visualization.png")
    
    print(f"Analysis complete. Results saved with prefix: {output_prefix}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze geometric distortions due to coordinate reprojection")
    parser.add_argument("shapefile", help="Path to input shapefile")
    parser.add_argument("--source_crs", help="Source CRS (optional, will use shapefile CRS if not specified)")
    parser.add_argument("--target_crs", default="EPSG:5937", help="Target CRS (default: EPSG:5937)")
    parser.add_argument("--output", help="Output prefix for result files")
    
    args = parser.parse_args()
    
    main(args.shapefile, args.source_crs, args.target_crs, args.output)
