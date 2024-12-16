import os
import csv
import glob

# Specify the path where your CSV files are located
csv_folder_path = 'C:/shubham_data/Project_data/pred_csv/'

# Get the list of all CSV files in the folder
csv_files = glob.glob(csv_folder_path + "*.csv")

# Dictionary to store the combined data, where the key is the image_id and the value is another dictionary of parameters
combined_data = {}

# Iterate through each CSV file
for file in csv_files:
    # Extract the parameter name from the filename (assumes the filename is the parameter)
    parameter_name = os.path.basename(file).split('.')[0].split('_')[1]  # Adjust this as per your file naming convention

    # Open the current CSV file and read it
    with open(file, mode='r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            image_id = row['image_id']
            pred_value = row['predication']
            
            # If the image_id is not already in the combined_data, add it
            if image_id not in combined_data:
                combined_data[image_id] = {}
            
            # Add the predicted value for this parameter
            combined_data[image_id][parameter_name] = pred_value

# Write the combined data to a new CSV file
with open('combined_predictions.csv', mode='w', newline='') as f:
    # Get the header (all parameter names) by checking the first entry in the combined_data
    all_params = sorted(next(iter(combined_data.values())).keys())
    fieldnames = ['image_id'] + all_params
    
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()

    # Write each image_id and its associated parameter values
    for image_id, params in combined_data.items():
        row = {'image_id': image_id}
        row.update(params)
        writer.writerow(row)

print("Combined CSV file has been created successfully!")
