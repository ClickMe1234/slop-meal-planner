class DataImportError(RuntimeError):
    code = "DATA_IMPORT_ERROR"


class DatasetFormatError(DataImportError):
    code = "DATASET_FORMAT_ERROR"


class ProviderConfigurationError(DataImportError):
    code = "PROVIDER_NOT_CONFIGURED"


class ProviderResponseError(DataImportError):
    code = "PROVIDER_RESPONSE_ERROR"
