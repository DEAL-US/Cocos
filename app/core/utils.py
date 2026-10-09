import os
import tempfile
import zipfile

# Module import: core.models imports this module at load time.
from core import models as core_models

def upload_file(file, user, file_type):
    """Upload a file to the system, associating it with a user and file type."""
    if not file:
        raise ValueError("No file provided for upload.")

    file_obj = core_models.File(user=user, file_type=file_type)

    file_obj.file.save(file.name, file, save=True)

    return file_obj

def create_file_zip(uploads):
    temp_file = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
    temp_file.close()

    try:
        with zipfile.ZipFile(temp_file.name, 'w', compression=zipfile.ZIP_DEFLATED) as zip_file:

            for upload in uploads:
                filename = os.path.basename(upload.file.name)

                with upload.file.open('rb') as source:
                    with zip_file.open(filename, 'w') as destination:
                        while chunk := source.read(1024 * 1024):
                            destination.write(chunk)

        return temp_file.name

    except Exception:
        os.unlink(temp_file.name)
        raise