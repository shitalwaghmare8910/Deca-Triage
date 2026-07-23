# scripts/upload_pdfs_to_gcs.py

import os
import glob
import logging
from google.cloud import storage
from google.api_core import exceptions

# --- Configuration ---
# You can hardcode these for the script, or load from your .env file for consistency.
# Ensure your local PDFs are in this directory.
LOCAL_PDF_DIRECTORY = "knowledge_base_pdfs"

# The GCS bucket you provided.
GCS_BUCKET_NAME = "db-dev-euwe3-gcs-173353-bucket-6ly4"

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def upload_pdfs_to_gcs(bucket_name: str, source_directory: str):
    """
    Scans a local directory for PDF files and uploads them to a specified GCS bucket.

    Args:
        bucket_name (str): The name of the target GCS bucket.
        source_directory (str): The local directory containing PDF files.
    """
    if not os.path.isdir(source_directory):
        logger.error(f"Source directory not found: '{source_directory}'")
        return

    try:
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(bucket_name)
        logger.info(f"Successfully connected to bucket: '{bucket_name}'")
    except exceptions.NotFound:
        logger.error(f"Error: Bucket '{bucket_name}' does not exist.")
        return
    except exceptions.Forbidden:
        logger.error(
            f"Error: Permission denied for bucket '{bucket_name}'. "
            "Ensure you have 'Storage Object Creator' or 'Storage Object Admin' role."
        )
        return
    except Exception as e:
        logger.error(f"An unexpected error occurred connecting to GCS: {e}")
        return

    # Find all .pdf files in the source directory
    pdf_files = glob.glob(os.path.join(source_directory, "*.pdf"))

    if not pdf_files:
        logger.warning(f"No PDF files found in '{source_directory}'. Nothing to upload.")
        return

    logger.info(f"Found {len(pdf_files)} PDF(s) to upload.")
    successful_uploads = 0
    failed_uploads = 0

    for local_file_path in pdf_files:
        try:
            file_name = os.path.basename(local_file_path)
            # The 'blob' is the object in GCS
            blob = bucket.blob(file_name)

            logger.info(f"Uploading '{file_name}' to gs://{bucket_name}/{file_name}...")
            
            # Perform the upload
            blob.upload_from_filename(local_file_path)
            
            successful_uploads += 1
        except Exception as e:
            logger.error(f"Failed to upload '{file_name}': {e}")
            failed_uploads += 1

    # --- Final Summary ---
    print("\n" + "="*30)
    logger.info("Upload process complete.")
    logger.info(f"Successfully uploaded: {successful_uploads} files")
    logger.info(f"Failed to upload:     {failed_uploads} files")
    print("="*30)


if __name__ == "__main__":
    # This block runs when you execute the script directly
    upload_pdfs_to_gcs(GCS_BUCKET_NAME, LOCAL_PDF_DIRECTORY)
