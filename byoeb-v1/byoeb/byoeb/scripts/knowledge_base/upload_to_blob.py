import os
import asyncio
from tqdm.asyncio import tqdm
from azure.identity import DefaultAzureCredential
from byoeb_integrations.media_storage.azure.async_azure_blob_storage import AsyncAzureBlobStorage
from glob import glob
from byoeb.kb_app.configuration.dependency_setup import amedia_storage

async def upload_file_to_blob(media_storage: AsyncAzureBlobStorage, file_path, folder_name="raw_documents"):
    blob_file_name = f"{folder_name}/{os.path.basename(file_path)}"
    await media_storage.aupload_file(  # Ensure this method exists
        file_path=file_path,
        file_name=blob_file_name
    )
    
async def upload_folder_to_blob(media_storage: AsyncAzureBlobStorage, folder_path):
    txt_file_paths = glob(os.path.join(folder_path, "*.txt"))

    # Run uploads concurrently for better performance
    await asyncio.gather(*(upload_file(media_storage, file) for file in tqdm(txt_file_paths, desc="Uploading files")))

async def get_files_in_blob(media_storage: AsyncAzureBlobStorage):
    files = await media_storage.aget_all_files_properties()
    print(files[:5])
    
async def upload_folder():
    folder_path = "/home/rash598/rash598_byoeb/byoeb/byoeb-v1/byoeb/byoeb/update_documents"
    account_url = "https://khushibabyashastorage.blob.core.windows.net"
    container_name = "ashacontainer"

    await upload_folder_to_blob(amedia_storage, folder_path)
    await amedia_storage._close()

async def upload_file():
    account_url = "https://khushibabyashastorage.blob.core.windows.net"
    container_name = "ashacontainer"

    file_path = "/home/rash598/Khushi/byoeb/byoeb-v1/byoeb/byoeb/scripts/knowledge_base/laado_scheme.txt"
    await upload_file_to_blob(amedia_storage, file_path)
    await amedia_storage._close()

if __name__ == "__main__":
    asyncio.run(upload_file())

