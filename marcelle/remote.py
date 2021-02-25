from glob import glob
import filetype
import os
import requests
import shutil
from tensorflow import keras
import tensorflowjs as tfjs
import keras2onnx


class Remote:
    def __init__(
        self,
        backend_root="http://localhost:3030",
        save_format="tfjs",
        source="keras",
    ):
        super().__init__()
        self.backend_root = backend_root + ("" if backend_root[-1] == "/" else "/")
        self.save_format = save_format
        self.runs_url = self.backend_root + "runs"
        self.models_url = self.backend_root + f"{save_format}-models"
        self.assets_url = self.backend_root + "assets"
        self.source = source
        self.run_id = None

    def create(self, run_data=None):
        try:
            res = requests.post(self.runs_url, json=run_data)
            if res.status_code != 201:
                print(
                    "Error: Could not create run. Improve error message."
                    f"HTTP Status Code: {res.status_code}"
                )
            else:
                self.run_id = res.json()["_id"]
        except requests.exceptions.RequestException:
            print("Warning: could not reach Marcelle backend at " + str(self.runs_url))

    def update(self, run_data=None):
        if not self.run_id:
            print("Warning: could not reach Marcelle backend at " + str(self.runs_url))
            return
        try:
            res = requests.patch(
                self.runs_url + "/" + self.run_id,
                json=run_data,
            )
            if res.status_code != 200:
                print("An error occured with HTTP Status Code:", res.status_code)
        except requests.exceptions.RequestException:
            print("Warning: could not reach Marcelle backend at " + str(self.runs_url))

    def upload_model(self, path_to_model, local_format, metadata={}):
        if self.save_format not in ["tfjs", "onnx"]:
            raise Exception(
                f"Unknown save format `{self.save_format}`." "Must be `tfjs` or `onnx`."
            )
        if local_format not in ["h5", "saved_model"]:
            raise Exception(
                "Unsupported local model format," "options are: 'h5' and 'saved_model'."
            )
        if self.save_format == "tfjs":
            if local_format == "h5":
                reconstructed_model = keras.models.load_model(path_to_model)
                print("reconstructed_model (h5)", reconstructed_model)
                tmp_path = "~tmp-tfjs~"
                tfjs.converters.save_keras_model(reconstructed_model, tmp_path)
            elif local_format == "saved_model":
                tmp_path = "~tmp-tfjs~"
                tfjs.converters.convert_tf_saved_model(
                    path_to_model,
                    tmp_path,
                    control_flow_v2=False,
                    experiments=False,
                    metadata=metadata,
                )
            res = self.upload_tfjs_model(tmp_path, metadata)
            shutil.rmtree(tmp_path)
            return res
        elif self.save_format == "onnx":
            if self.source == "keras":
                reconstructed_model = keras.models.load_model(path_to_model)
                onnx_model = keras2onnx.convert_keras(
                    reconstructed_model, reconstructed_model.name
                )
                tmp_path = "~tmp-onnx~"
                keras2onnx.save_model(onnx_model, tmp_path)
                res = self.upload_onnx_model(tmp_path, metadata)
                shutil.rmtree(tmp_path)
                return res
            else:
                raise Exception(
                    "Only 'keras' source is implemented for ONNX at the moment"
                )

    def upload_tfjs_model(self, tmp_path, metadata={}):
        files = []
        json_file = open(os.path.join(tmp_path, "model.json"), "r")
        files.append(("model.json", ("model.json", json_file, "application/json")))
        model_files = glob(os.path.join(tmp_path, "*.bin"))
        bin_files = [open(model_file, "rb") for model_file in model_files]
        for i, f in enumerate(bin_files):
            files.append(
                (
                    os.path.basename(model_files[i]),
                    (os.path.basename(model_files[i]), f, "application/octet-stream"),
                )
            )
        model_url = None
        try:
            res = requests.post(self.models_url + "/upload", files=files)
            if res.status_code != 200:
                print("An error occured with HTTP Status Code:", res.status_code)
                print(res.json()["error"])
                return {}
            model_url = res.json()["model.json"]
        except requests.exceptions.RequestException:
            print(
                "Warning: could not reach Marcelle backend at "
                + str(self.models_url + "/upload")
            )
        json_file.close()
        [f.close() for f in bin_files]
        if not model_url:
            return {}
        try:
            res = requests.post(
                self.models_url,
                json={
                    **metadata,
                    "url": model_url,
                    "format": self.save_format,
                },
            )
            if res.status_code != 201:
                print("An error occured with HTTP Status Code:", res.status_code)
            return res.json()
        except requests.exceptions.RequestException:
            print(
                "Warning: could not reach Marcelle backend at " + str(self.models_url)
            )
            return {}

    def upload_onnx_model(self, tmp_path, metadata={}):
        if ".onnx" not in tmp_path:
            tmp_path = f"{tmp_path}.onnx"
        onnx_file = open(tmp_path, "rb")
        filename = os.path.basename(tmp_path)
        files = [(filename, (filename, onnx_file, "application/octet-stream"))]
        model_url = None
        try:
            res = requests.post(self.models_url + "/upload", files=files)
            if res.status_code != 200:
                print("An error occured with HTTP Status Code:", res.status_code)
                print(res.json()["error"])
                return {}
            model_url = res.json()[filename]
        except requests.exceptions.RequestException:
            print(
                "Warning: could not reach Marcelle backend at "
                + str(self.models_url + "/upload")
            )
        onnx_file.close()
        if not model_url:
            return {}
        try:
            res = requests.post(
                self.models_url,
                json={
                    **metadata,
                    "url": model_url,
                    "format": self.save_format,
                },
            )
            if res.status_code != 201:
                print("An error occured with HTTP Status Code:", res.status_code)
            return res.json()
        except requests.exceptions.RequestException:
            print(
                "Warning: could not reach Marcelle backend at " + str(self.models_url)
            )
            return {}

    def upload_asset(self, path_to_asset, metadata={}):
        asset_file = open(path_to_asset, "rb")
        kind = filetype.guess(path_to_asset)
        if kind is None:
            extension = os.path.splitext(path_to_asset)[1]
            mime = "application/octet-stream"
        else:
            extension = f".{kind.extension}"
            mime = kind.mime

        filename = os.path.basename(path_to_asset)
        files = [(filename, (filename, asset_file, mime))]
        asset_url = None
        try:
            res = requests.post(self.assets_url + "/upload", files=files)
            if res.status_code != 200:
                print("An error occured with HTTP Status Code:", res.status_code)
                print(res.json()["error"])
                return {}
            asset_url = res.json()[filename]
        except requests.exceptions.RequestException:
            print(
                "Warning: could not reach Marcelle backend at "
                + str(self.assets_url + "/upload")
            )
        asset_file.close()
        if not asset_url:
            return {}
        try:
            res = requests.post(
                self.assets_url,
                json={
                    **metadata,
                    "filename": filename,
                    "extension": extension,
                    "mime": mime,
                    "url": asset_url,
                },
            )
            if res.status_code != 201:
                print("An error occured with HTTP Status Code:", res.status_code)
            return res.json()
        except requests.exceptions.RequestException:
            print(
                "Warning: could not reach Marcelle backend at " + str(self.assets_url)
            )
            return {}

    def retrieve_run(self, run_start_at):
        run_data = False
        try:
            res = requests.get(
                self.runs_url + f"?source={self.source}&run_start_at={run_start_at}"
                "&$sort[createdAt]=-1"
            )
            if res.status_code != 200:
                print(f"An error occured with HTTP Status Code: {res.status_code}")
            else:
                res_json = res.json()
                if res_json["total"] > 0:
                    self.run_id = res_json["data"][0]["_id"]
                    run_data = res_json["data"][0]
        except requests.exceptions.RequestException:
            print("Warning: could not reach Marcelle backend at " + str(self.runs_url))
        return run_data

    def remove_run(self, run_data):
        for checkpoint in run_data["checkpoints"]:
            try:
                req_url = self.models_url + "/" + checkpoint["_id"]
                res = requests.delete(req_url)
                print("remove: res.status_code=", res.status_code)
                if res.status_code != 200:
                    print(
                        f"An error occured with HTTP Status Code: {res.status_code}\n"
                        f"Request URL: {req_url}"
                    )
            except requests.exceptions.RequestException:
                print(
                    "Warning: could not reach Marcelle backend at "
                    + str(self.models_url)
                )
        try:
            res = requests.delete(self.runs_url + "/" + run_data["_id"])
            print("remove: res.status_code=", res.status_code)
            if res.status_code != 200:
                print(f"An error occured with HTTP Status Code: {res.status_code}")
            else:
                res_json = res.json()
                start_date = res_json["run_start_at"]
                print(f"Removed run {id} from server (run start date: {start_date})")
            return True
        except requests.exceptions.RequestException:
            print("Warning: could not reach Marcelle backend at " + str(self.runs_url))
            return False
