from pathlib import Path

from hackster_studio.automation.comfyui_engine import (
    comfyui_history_error,
    default_flux_pulid_workflow,
    prepare_workflow,
)


def test_flux_pulid_workflow_wires_reference_model() -> None:
    workflow = default_flux_pulid_workflow()

    assert workflow["12"]["class_type"] == "ApplyPulidFlux"
    assert workflow["12"]["inputs"]["model"] == ["1", 0]
    assert workflow["12"]["inputs"]["pulid_flux"] == ["13", 0]
    assert workflow["12"]["inputs"]["eva_clip"] == ["14", 0]
    assert workflow["12"]["inputs"]["face_analysis"] == ["15", 0]
    assert workflow["12"]["inputs"]["image"] == ["16", 0]
    assert workflow["2"]["inputs"]["model"] == ["12", 0]


def test_prepare_workflow_injects_reference_image_name() -> None:
    workflow = prepare_workflow(
        default_flux_pulid_workflow(),
        "Niko in Cyber Forest",
        Path("page_004.png"),
        reference_image_name="approved_niko.png",
    )

    assert workflow["16"]["inputs"]["image"] == "approved_niko.png"


def test_comfyui_history_error_extracts_execution_failure() -> None:
    entry = {
        "status": {
            "status_str": "error",
            "messages": [
                [
                    "execution_error",
                    {
                        "node_type": "KSampler",
                        "exception_type": "TypeError",
                        "exception_message": "forward_orig() got an unexpected keyword argument 'timestep_zero_index'\n",
                    },
                ]
            ],
        }
    }

    assert comfyui_history_error(entry) == (
        "KSampler TypeError: forward_orig() got an unexpected keyword argument 'timestep_zero_index'"
    )
