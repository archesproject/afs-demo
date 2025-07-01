import datetime
import logging
import json
import os
import uuid
from django.http import HttpRequest
from django.utils.translation import gettext as _
from django.views.generic import View
from arches.app.models.models import File, IIIFManifest, VwAnnotation, ManifestValidationError
from arches.app.utils.response import JSONResponse

logger = logging.getLogger(__name__)


class CreateManifest(View):
    def create_manifest(
        self, name="", desc="", file_url="file_url", attribution="", logo="", canvases=[]
    ):
        metadata = []  # {"label": "TBD", "value": ["Unknown", ...]}
        sequence_id = f"{self.cantaloupe_uri}/manifest/sequence/TBD.json"

        return {
            "@context": "http://iiif.io/api/presentation/2/context.json",
            "@type": "sc:Manifest",
            "description": desc,
            "label": name,
            "attribution": attribution,
            "logo": logo,
            "metadata": metadata,
            "thumbnail": {
                "@id": file_url + "/full/!300,300/0/default.jpg",
                "@type": "dctypes:Image",
                "format": "image/jpeg",
                "label": "Main View (.45v)",
            },
            "sequences": [
                {
                    "@id": sequence_id,
                    "@type": "sc:Sequence",
                    "canvases": canvases,
                    "label": "Object",
                    "startCanvas": "",
                }
            ],
        }

    def create_canvas(self, image_json, file_url, file_name, image_id):
        canvas_id = f"{self.cantaloupe_uri}/manifest/canvas/{image_id}.json"
        image_id = f"{self.cantaloupe_uri}/manifest/annotation/{image_id}.json"
        thumbnail_width = 300 if image_json["width"] >= 300 else image_json["width"]
        thumbnail_height = (
            300 if image_json["height"] >= 300 else image_json["height"]
        )
        thumbnail_id = (
            f"{file_url}/full/!{thumbnail_width},{thumbnail_height}/0/default.jpg"
        )

        return {
            "@id": canvas_id,
            "@type": "sc:Canvas",
            "height": image_json["height"],
            "width": image_json["width"],
            "images": [
                {
                    "@id": image_id,
                    "@type": "oa.Annotation",
                    "motivation": "unknown",
                    "on": canvas_id,
                    "resource": {
                        "@id": file_url + "/full/full/0/default.jpg",
                        "@type": "dctypes:Image",
                        "format": "image/jpeg",
                        "height": image_json["height"],
                        "width": image_json["width"],
                        "service": {
                            "@context": "http://iiif.io/api/image/2/context.json",
                            "@id": file_url,
                            "profile": "http://iiif.io/api/image/2/level2.json",
                        },
                    },
                }
            ],
            "label": f"{file_name}",
            "license": "TBD",
            "thumbnail": {
                "@id": thumbnail_id,
                "@type": "dctypes:Image",
                "format": "image/jpeg",
                "service": {
                    "@context": "http://iiif.io/api/image/2/context.json",
                    "@id": file_url,
                    "profile": "http://iiif.io/api/image/2/level2.json",
                },
            },
        }

    def add_canvases(self, manifest, canvases):
        manifest.manifest["sequences"][0]["canvases"] += canvases

    def check_canvas_in_use(cself, canvas_id):
        return VwAnnotation.objects.filter(canvas=canvas_id).exists()

    def delete_canvases(self, manifest, canvases_to_remove):
        canvas_ids_remove = [
            canvas["images"][0]["resource"]["service"]["@id"]
            for canvas in canvases_to_remove
        ]
        canvases_in_use = []
        for canvas_id in canvas_ids_remove:
            if self.check_canvas_in_use(canvas_id):
                canvases_in_use.append(canvas_id)
        canvases = manifest.manifest["sequences"][0]["canvases"]
        if len(canvases_in_use) > 0:
            canvas_labels_in_use = [
                item["label"]
                for item in canvases
                if item["images"][0]["resource"]["service"]["@id"]
                in canvases_in_use
            ]
            raise ManifestValidationError(
                "The following canvases cannot be deleted because they have resource annotations: {}".format(
                    ", ".join(canvas_labels_in_use)
                )
            )
        manifest.manifest["sequences"][0]["canvases"] = [
            canvas
            for canvas in canvases
            if canvas["images"][0]["resource"]["service"]["@id"]
            not in canvas_ids_remove
        ]

    def create_image(self, file, scheme, host):
        new_image_id = uuid.uuid4()
        new_image_file = File.objects.create(fileid=new_image_id, path=file)
        new_image_file.save()

        file_name = os.path.basename(new_image_file.path.name)
        file_url = (
            f"{scheme}://{host}/iiifserver/iiif/2/{file_name}"
        )
        file_json_url = f"{self.cantaloupe_uri}/2/{file_name}/info.json"
        image_json = self.fetch(file_json_url)

        return image_json, new_image_id, file_url

    def change_manifest_info(self, manifest, name, desc, attribution, logo):
        if name is not None and name != "":
            manifest.label = name
            manifest.manifest["label"] = name
        if desc is not None and desc != "":
            manifest.description = desc
            manifest.manifest["description"] = desc
        if attribution and attribution != "":
            manifest.manifest["attribution"] = attribution
        if logo and logo != "":
            manifest.manifest["logo"] = logo

    def change_manifest_metadata(self, manifest, metadata):  # To be fixed
        manifest.manifest["metadata"] = metadata

    def change_canvas_label(self, manifest, canvas_id, label):
        # canvas_id = canvas['images'][0]['resource']['service']['@id']
        canvases = manifest.manifest["sequences"][0]["canvases"]
        for canvas in canvases:
            if canvas["images"][0]["resource"]["service"]["@id"] == canvas_id:
                canvas["label"] = label

    def post(self, request: HttpRequest):
        acceptable_types = [
            ".jpg",
            ".jpeg",
            ".tiff",
            ".tif",
            ".png",
        ]

        files = request.FILES.getlist("files")
        name = request.POST.get("manifest_title")
        if name == "null" or name == "undefined":
            try:
                name = os.path.splitext(files[0].name)[0]
            except:
                pass

        attribution = request.POST.get("manifest_attribution", "")
        logo = request.POST.get("manifest_logo", "")
        desc = request.POST.get("manifest_description", "")
        operation = request.POST.get("operation")
        manifest_url = request.POST.get("manifest")
        canvas_label = request.POST.get("canvas_label")
        canvas_id = request.POST.get("canvas_id")
        metadata = request.POST.get("metadata")
        transaction_id = request.POST.get("transaction_id", uuid.uuid1())
        selected_canvases = request.POST.get("selected_canvases")
        scheme = request.scheme
        host = request.get_host()
        try:
            metadata = json.loads(request.POST.get("metadata"))
        except TypeError:
            metadata = []

        if operation == "create":
            canvases = []
            for f in files:
                if os.path.splitext(f.name)[1].lower() in acceptable_types:
                    image_json, image_id, file_url = self.create_image(f, scheme, host)

                    canvas = self.create_canvas(
                        image_json, file_url, os.path.splitext(f.name)[0], image_id
                    )
                    canvases.append(canvas)
                else:
                    logger.warning("filetype unacceptable: " + f.name)

            pres_dict = self.create_manifest(
                name=name,
                canvases=canvases,
                file_url=canvases[0]["thumbnail"]["service"]["@id"],
            )
            manifest_global_id = str(uuid.uuid4())
            json_url = f"/manifest/{manifest_global_id}"
            pres_dict["@id"] = f"{request.scheme}://{request.get_host()}{json_url}"

            manifest = IIIFManifest.objects.create(
                label=name,
                description=desc,
                manifest=pres_dict,
                url=json_url,
                globalid=manifest_global_id,
                transactionid=transaction_id,
            )

            return JSONResponse(manifest)
        else:
            manifest = IIIFManifest.objects.get(url=manifest_url)

        self.change_manifest_info(manifest, name, desc, attribution, logo)

        if canvas_label is not None:
            self.change_canvas_label(manifest, canvas_id, canvas_label)

        if selected_canvases is not None:
            selected_canvases_json = json.loads(selected_canvases)
            try:
                self.delete_canvases(manifest, selected_canvases_json)
            except ManifestValidationError as e:
                return JSONResponse({"message": e.message}, status=500)

        if len(files) > 0:
            try:
                canvases = []
                for f in files:
                    if os.path.splitext(f.name)[1].lower() in acceptable_types:
                        image_json, image_id, file_url = self.create_image(f, scheme, host)
                        canvas = self.create_canvas(
                            image_json, file_url, os.path.splitext(f.name)[0], image_id
                        )
                        canvases.append(canvas)
                    else:
                        logger.warning("filetype unacceptable: " + f.name)
                self.add_canvases(manifest, canvases)
            except:
                logger.warning("You have to select a manifest to add images")
                raise

        self.change_manifest_metadata(manifest, manifest)

        manifest.save()
        return JSONResponse(manifest)