import os
import zipfile
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.tool.base import BaseTool

Command = Literal[
    "zip",
    "unzip",
]


class ZipFileHandler(BaseTool):
    name: str = "zip_file_handler"
    description: str = """Handle zipping and unzipping of files.
    Use this tool to compress files into a zip archive or extract files from a zip archive.
    """
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "(required) The operation to perform. 'zip' to compress files, 'unzip' to extract files.",
                "enum": ["zip", "unzip"],
            },
            "input_paths": {
                "type": "array",
                "items": {
                    "type": "string",
                    "description": "(required for 'zip') Paths to the files or directories to be compressed.",
                },
                "description": "Paths to the input files or directories.",
            },
            "output_path": {
                "type": "string",
                "description": "(required) The path where the zip archive should be created (for 'zip') or where the files should be extracted (for 'unzip'), including filename and extension.",
            },
            "password": {
                "type": "string",
                "description": "(optional) Password to encrypt the zip archive or to decrypt it during extraction.",
                "default": None,
            },
        },
        "required": ["command", "input_paths"],
    }

    async def execute(
        self,
        *,
        command: Command,
        input_paths: list[str],
        output_path: str | None = None,
        password: str | None = None,
    ) -> Dict:
        """
        Execute the ZIP operation based on the command.
        Args: Keyword arguments passed to the ZIP operation.
            - For 'zip' command: `input_paths` (list of file paths to compress) and `output_path` (path to save the ZIP archive).
            - For 'unzip' command: `input_paths` (path to the ZIP archive) and `output_path` (directory to extract files to).
        Returns:
        Dict: Contains 'output' with execution output or error message and 'success' status.
        """
        if command == "zip":
            if not isinstance(input_paths, list) or not input_paths:
                return {
                    "observation": "Invalid input paths specified",
                    "success": False,
                }
            return await self._compress(input_paths, output_path)
        elif command == "unzip":
            if not isinstance(input_paths, list) or len(input_paths) != 1:
                return {"observation": "Invalid input path specified", "success": False}
            return await self._decompress(input_paths[0], output_path)
        else:
            return {"observation": "Invalid command specified", "success": False}

    # Compress method
    async def _compress(self, files: List[str], output_zip: str) -> str:
        """
        Compress multiple files into a ZIP archive.
        Args:
        files (List[str]): List of file paths to compress.
        output_zip (str): Path where the ZIP archive should be saved.
        Returns:
        str: A message indicating the result of the operation.
        """
        try:
            with zipfile.ZipFile(output_zip, "w") as zipf:
                for file in files:
                    zipf.write(file, os.path.basename(file))
            return {
                "observation": f"Files successfully compressed into {output_zip}",
                "success": True,
            }
        except Exception as e:
            return {
                "observation": f"Error compressing files: {str(e)}",
                "success": False,
            }

    # Decompress method
    async def _decompress(self, zip_file: str, output_dir: str) -> str:
        """
        Decompress a ZIP archive to a specified directory.
        Args:
        zip_file (str): Path to the ZIP archive.
        output_dir (str): Directory where the files should be extracted.
        Returns:
        str: A message indicating the result of the operation.
        """
        try:
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            with zipfile.ZipFile(zip_file, "r") as zipf:
                zipf.extractall(output_dir)
            return {
                "observation": f"ZIP archive successfully decompressed to {output_dir}",
                "success": True,
            }
        except Exception as e:
            return {
                "observation": f"Error decompressing ZIP file: {str(e)}",
                "success": False,
            }
