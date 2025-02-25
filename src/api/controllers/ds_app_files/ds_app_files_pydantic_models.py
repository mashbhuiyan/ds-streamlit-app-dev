from pydantic import BaseModel, Field


class DsAppFilesRequest(BaseModel):
    pass


class DsAppFilesResponse(BaseModel):
    file_exists: bool = Field(...,
                              description="File exists on S3"
                              )
    presigned_url: str | None = Field(...,
                               description="Presigned URL for the file. null if the file doesn't exist",
                               examples=["https://example.com/file.csv"])
    md5sum: str | None = Field(...,
                               description="MD5 Sum of the file. null if the file doesn't exist",
                               examples=["2d7ed4bd364a44715f35e5bfa3e0193a"])


class CustomRequestHeaders(BaseModel):
    authorization: str = Field(..., description="Authorization header",
                               examples=["Bearer token"])
