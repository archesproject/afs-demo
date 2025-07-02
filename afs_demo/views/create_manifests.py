import logging
import json
import os
import requests
import uuid
from django.db import connection
from django.http import HttpRequest
from django.utils.translation import gettext as _
from django.views.generic import View
from arches.app.models.models import File, IIIFManifest, TileModel
from arches.app.models.system_settings import settings
from arches.app.utils.response import JSONResponse

logger = logging.getLogger(__name__)


ARCHES_URL = settings.PUBLIC_SERVER_ADDRESS.rstrip("/")
CANTALOUPE_URI = f"{settings.CANTALOUPE_HTTP_ENDPOINT.rstrip('/')}/iiif"
ACCEPTABLE_TYPES = [
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".png",
]


def create_manifest_json(
    name="",
    desc="",
    file_url="file_url",
    attribution="",
    logo="",
    canvases=[],
    metadata=[],
):
    sequence_id = f"{CANTALOUPE_URI}/manifest/sequence/TBD.json"

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


def create_canvas(image_json, file_url, file_name, image_id):
    canvas_id = f"{CANTALOUPE_URI}/manifest/canvas/{image_id}.json"
    image_id = f"{CANTALOUPE_URI}/manifest/annotation/{image_id}.json"
    thumbnail_width = 300 if image_json["width"] >= 300 else image_json["width"]
    thumbnail_height = 300 if image_json["height"] >= 300 else image_json["height"]
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


def fetch(url):
    try:
        resp = requests.get(url)
        return resp.json()
    except:
        logger.warning("Manifest not created. Check if Cantaloupe running")
        raise


def create_image(file):
    new_image_id = uuid.uuid4()
    new_image_file = File.objects.create(fileid=new_image_id, path=file)
    new_image_file.save()

    file_name = os.path.basename(new_image_file.path.name)
    file_url = f"{ARCHES_URL}/iiifserver/iiif/2/{file_name}"
    file_json_url = f"{CANTALOUPE_URI}/2/{file_name}/info.json"
    image_json = fetch(file_json_url)

    return image_json, new_image_id, file_url


def create_manifest_record(
    name, desc, transaction_id, pres_dict, json_url, manifest_global_id, sql
):
    if sql:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO iiif_manifests (
                    label,
                    description,
                    manifest,
                    url,
                    globalid,
                    transactionid
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    name,
                    desc,
                    pres_dict,
                    json_url,
                    manifest_global_id,
                    transaction_id,
                ),
            )
    else:
        manifest = IIIFManifest.objects.create(
            label=name,
            description=desc,
            manifest=pres_dict,
            url=json_url,
            globalid=manifest_global_id,
            transactionid=transaction_id,
        )

    return manifest


# this function is the main entry point for creating a manifest service
def create_manifest_service(
    files,
    name="",
    desc="",
    attribution="",
    logo="",
    transaction_id=None,
    metadata=[],
):
    if not name:
        try:
            name = os.path.splitext(files[0]["name"])[0]
        except IndexError:
            name = _("Untitled Manifest")

    canvases = []
    for f in files:
        image_json, image_id, file_url = get_image_info(f)

        canvas = create_canvas(
            image_json, file_url, os.path.splitext(f["name"])[0], image_id
        )
        canvases.append(canvas)

    if canvases:
        pres_dict = create_manifest_json(
            name=name,
            canvases=canvases,
            file_url=canvases[0]["thumbnail"]["service"]["@id"],
            desc=desc,
            attribution=attribution,
            logo=logo,
            metadata=metadata,
        )
        manifest_global_id = str(uuid.uuid4())
        json_url = f"/manifest/{manifest_global_id}"
        pres_dict["@id"] = f"{ARCHES_URL}{json_url}"

        manifest = create_manifest_record(
            name, desc, transaction_id, pres_dict, json_url, manifest_global_id, False
        )

    return manifest


def get_image_info(file):
    file_id = file["file_id"]
    file_name = os.path.basename(file["name"])
    file_url = f"{ARCHES_URL}/iiifserver/iiif/2/{file_name}"
    file_json_url = f"{CANTALOUPE_URI}/2/{file_name}/info.json"
    image_json = fetch(file_json_url)

    return image_json, file_id, file_url


def create_manifests_from_tiles():
    DIGITAL_RESOURCES_NODEGROUPID = "7c486328-d380-11e9-b88e-a4d18cec433a"
    digital_resource_file_tiles = TileModel.objects.filter(
        nodegroup_id=DIGITAL_RESOURCES_NODEGROUPID,
    ).iterator()
    transaction_id = uuid.uuid1()
    for tile in digital_resource_file_tiles:
        for file in tile.data[DIGITAL_RESOURCES_NODEGROUPID]:
            if file["file_id"] is not None and file["file_id"] != "":
                if os.path.splitext(file["name"])[1].lower() in ACCEPTABLE_TYPES:
                    create_manifest_service([file], transaction_id=transaction_id)
                else:
                    logger.warning("filetype unacceptable: " + file["name"])


class CreateManifest(View):
    def post(request: HttpRequest):
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
        transaction_id = request.POST.get("transaction_id", uuid.uuid1())
        scheme = request.scheme
        host = request.get_host()
        try:
            metadata = json.loads(request.POST.get("metadata"))
        except TypeError:
            metadata = []

        manifest = create_manifest_service(
            files, name, desc, attribution, logo, transaction_id, metadata
        )

        return JSONResponse(manifest)
