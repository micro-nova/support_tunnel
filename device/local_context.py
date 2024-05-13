import os
import shutil

from invoke.context import Context

# Using this context object allows us to retain the bits of
# Fabric's Connection() that we use - namely `put` - to keep
# the wireguard tunnel creation code the same between
# local and remote.
# Docs:
# https://docs.pyinvoke.org/en/stable/api/context.html


class LocalContext(Context):
    def __init__(self, original_context):
        """ Redefine init to permit us to simply slurp up an existing
            context's config, instead of the caller having to be aware of this
            convention.
        """
        super().__init__(config=original_context.config)

    def put(self, local, remote, preserve_mode=True):
        """ 'put' a 'file' locally. This method tries to implement a minor subset of this interface:
             https://github.com/fabric/fabric/blob/988dd0fd05db47331cb43d0ea9787908ef33219c/fabric/transfer.py#L187
        """
        is_file_like = hasattr(local, "write") and callable(local.write)
        if not is_file_like:
            raise NotImplementedError(
                "local argument must be a file like object!")

        path = os.path.abspath(remote)
        with open(path, "w") as file:
            shutil.copyfileobj(local, file)
