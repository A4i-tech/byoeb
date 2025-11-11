"""
Script to upload files to Azure Blob Storage.
Uses environment variables and dependency_setup for configuration.
"""
import os
import sys
import asyncio
from tqdm.asyncio import tqdm
from glob import glob
from byoeb.kb_app.configuration.dependency_setup import amedia_storage

async def upload_file_to_blob(media_storage, file_path, folder_name="raw_documents"):
    """
    Upload a single file to blob storage.
    
    Args:
        media_storage: The media storage instance from dependency_setup
        file_path: Path to the file to upload
        folder_name: Folder name in blob storage (default: "raw_documents")
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    blob_file_name = f"{folder_name}/{os.path.basename(file_path)}"
    print(f"📤 Uploading: {os.path.basename(file_path)} → {blob_file_name}")
    await media_storage.aupload_file(
        file_path=file_path,
        file_name=blob_file_name
    )
    print(f"✅ Successfully uploaded: {os.path.basename(file_path)}")
    
async def upload_folder_to_blob(media_storage, folder_path, folder_name="raw_documents"):
    """
    Upload all .txt files from a folder to blob storage.
    
    Args:
        media_storage: The media storage instance from dependency_setup
        folder_path: Path to the folder containing files to upload
        folder_name: Folder name in blob storage (default: "raw_documents")
    """
    if not os.path.exists(folder_path):
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    
    txt_file_paths = glob(os.path.join(folder_path, "*.txt"))
    
    if not txt_file_paths:
        print(f"⚠️  No .txt files found in the specified folder")
        return
    
    print(f"📤 Found {len(txt_file_paths)} file(s) to upload")
    # Run uploads concurrently for better performance
    await asyncio.gather(*(upload_file_to_blob(media_storage, file, folder_name) for file in tqdm(txt_file_paths, desc="Uploading files")))

async def get_files_in_blob(media_storage):
    """Get list of files in blob storage (for debugging)."""
    files = await media_storage.aget_all_files_properties()
    # Only print file names, not full properties which may contain URLs or sensitive data
    if files:
        file_names = [f.get('name', 'Unknown') if isinstance(f, dict) else getattr(f, 'name', 'Unknown') for f in files[:5]]
        print(f"Found {len(files)} file(s). First 5 file names: {file_names}")
    else:
        print("No files found in blob storage")

def get_file_path_from_env_or_arg():
    """
    Get file path from environment variable or command line argument.
    Priority: command line arg > environment variable > default location
    """
    # Check command line argument
    if len(sys.argv) > 1:
        return sys.argv[1]
    
    # Check environment variable
    file_path = os.getenv("UPLOAD_FILE_PATH")
    if file_path:
        return file_path
    
    # Try to construct default path from APP_PATH and DATA_PATH
    app_path = os.getenv("APP_PATH")
    data_path = os.getenv("DATA_PATH")
    
    if app_path and data_path:
        # Default: upload the RI Manual that was recently converted
        default_file = "RI Manual For Medical Officers -Final September 12-1 (1).txt"
        default_path = os.path.join(app_path, data_path, "raw_documents", default_file)
        if os.path.exists(default_path):
            return default_path
    
    return None

def get_folder_path_from_env_or_arg():
    """
    Get folder path from environment variable or command line argument.
    Priority: command line arg > environment variable > default location
    """
    # Check command line argument
    if len(sys.argv) > 1:
        folder_path = sys.argv[1]
        if os.path.isdir(folder_path):
            return folder_path
    
    # Check environment variable
    folder_path = os.getenv("UPLOAD_FOLDER_PATH")
    if folder_path and os.path.isdir(folder_path):
        return folder_path
    
    # Try to construct default path from APP_PATH and DATA_PATH
    app_path = os.getenv("APP_PATH")
    data_path = os.getenv("DATA_PATH")
    
    if app_path and data_path:
        default_path = os.path.join(app_path, data_path, "raw_documents")
        if os.path.exists(default_path):
            return default_path
    
    return None

async def upload_file():
    """Upload a single file to blob storage."""
    from byoeb.kb_app.configuration.dependency_setup import container_name
    from byoeb.kb_app.configuration import config as env_config
    from byoeb.kb_app.configuration.config import app_config
    
    file_path = get_file_path_from_env_or_arg()
    
    if not file_path:
        print("❌ No file path provided!")
        print("\nUsage:")
        print("  python -m byoeb.scripts.knowledge_base.upload_to_blob <file_path>")
        print("  OR")
        print("  Set UPLOAD_FILE_PATH environment variable")
        print("  OR")
        print("  Set APP_PATH and DATA_PATH environment variables")
        return
    
    # Display configuration before upload
    print("\n" + "=" * 80)
    print("  UPLOAD CONFIGURATION VERIFICATION")
    print("=" * 80)
    
    # Get actual storage configuration
    if env_config.env_azure_storage_connection_string:
        conn_str = env_config.env_azure_storage_connection_string
        account_match = [part for part in conn_str.split(';') if part.startswith('AccountName=')]
        if account_match:
            account_name = account_match[0].split('=')[1]
            print(f"\n📍 Blob Storage Configuration:")
            print(f"  Account: {account_name[:8]}...")  # Only show first 8 chars for security
            print(f"  Container: {container_name}")
            print(f"  Full path: https://[account].blob.core.windows.net/{container_name}/")
    else:
        account_url = app_config["media_storage"]["azure"]["account_url"]
        # Sanitize account URL to avoid exposing full connection details
        if account_url:
            sanitized_url = account_url.split('@')[0] + '@...' if '@' in account_url else account_url[:50] + '...'
        else:
            sanitized_url = "Not configured"
        print(f"\n📍 Blob Storage Configuration:")
        print(f"  Account URL: {sanitized_url}")
        print(f"  Container: {container_name}")
    
    print(f"\n📍 File to upload:")
    print(f"  File name: {os.path.basename(file_path)}")
    print(f"  Blob path: raw_documents/{os.path.basename(file_path)}")
    print("=" * 80 + "\n")
    
    try:
        await upload_file_to_blob(amedia_storage, file_path, folder_name="raw_documents")
    finally:
        await amedia_storage._close()

async def upload_folder():
    """Upload all .txt files from a folder to blob storage."""
    folder_path = get_folder_path_from_env_or_arg()
    
    if not folder_path:
        print("❌ No folder path provided!")
        print("\nUsage:")
        print("  python -m byoeb.scripts.knowledge_base.upload_to_blob <folder_path>")
        print("  OR")
        print("  Set UPLOAD_FOLDER_PATH environment variable")
        print("  OR")
        print("  Set APP_PATH and DATA_PATH environment variables")
        return
    
    try:
        await upload_folder_to_blob(amedia_storage, folder_path, folder_name="raw_documents")
    finally:
        await amedia_storage._close()

if __name__ == "__main__":
    # Check if argument is a file or folder
    if len(sys.argv) > 1:
        arg_path = sys.argv[1]
        if os.path.isfile(arg_path):
            asyncio.run(upload_file())
        elif os.path.isdir(arg_path):
            asyncio.run(upload_folder())
        else:
            print(f"❌ Path not found: {os.path.basename(arg_path) if arg_path else 'None'}")
            sys.exit(1)
    else:
        # Default: try to upload a single file
        asyncio.run(upload_file())

