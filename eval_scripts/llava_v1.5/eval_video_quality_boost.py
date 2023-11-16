import argparse
import torch
import os

from llava.constants import IMAGE_TOKEN_INDEX, DEFAULT_IMAGE_TOKEN, DEFAULT_IM_START_TOKEN, DEFAULT_IM_END_TOKEN
from llava.conversation import conv_templates, SeparatorStyle
from llava.model.builder import load_pretrained_model
from llava.utils import disable_torch_init
from llava.mm_utils import tokenizer_image_token, get_model_name_from_path, KeywordsStoppingCriteria

from PIL import Image
from tqdm import tqdm

import requests
from PIL import Image
from io import BytesIO

from collections import defaultdict

from decord import VideoReader

os.makedirs("results/mix-llava-v1.5-7b-boost/", exist_ok=True)

def load_image(image_file):
    if image_file.startswith('http') or image_file.startswith('https'):
        response = requests.get(image_file)
        image = Image.open(BytesIO(response.content)).convert('RGB')
    else:
        image = Image.open(image_file).convert('RGB')
    return image

def load_video(video_file):
    vr = VideoReader(video_file)

    # Get video frame rate
    fps = vr.get_avg_fps()

    # Calculate frame indices for 1fps
    frame_indices = [int(fps * i) for i in range(int(len(vr) / fps))]

    return [Image.fromarray(vr[index].asnumpy()) for index in frame_indices]

def eval_model(args):
    # Model
    disable_torch_init()

    model_name = get_model_name_from_path(args.model_path)
    tokenizer, model, image_processor, context_len = load_pretrained_model(args.model_path, args.model_base, model_name, True)

    qs = args.query
    if model.config.mm_use_im_start_end:
        qs = DEFAULT_IM_START_TOKEN + DEFAULT_IMAGE_TOKEN + DEFAULT_IM_END_TOKEN + '\n' + qs
    else:
        qs = DEFAULT_IMAGE_TOKEN + '\n' + qs

    if 'llama-2' in model_name.lower():
        conv_mode = "llava_llama_2"
    elif "v1" in model_name.lower():
        conv_mode = "llava_v1"
    elif "mpt" in model_name.lower():
        conv_mode = "mpt"
    else:
        conv_mode = "llava_v0"

    if args.conv_mode is not None and conv_mode != args.conv_mode:
        print('[WARNING] the auto inferred conversation mode is {}, while `--conv-mode` is {}, using {}'.format(conv_mode, args.conv_mode, args.conv_mode))
    else:
        args.conv_mode = conv_mode

    conv = conv_templates[args.conv_mode].copy()
    conv.append_message(conv.roles[0], qs)
    conv.append_message(conv.roles[1], None)
    prompt = conv.get_prompt()
    #prompt += " The image quality is"
    
    import json

    
    image_paths = [
        "../datasets/KoNViD_1k_videos/",
        "../datasets/LIVE_VQC/Video/",
    ]

    json_prefix = "../datasets/json/"
    jsons = [
        json_prefix + "konvid.json",
        json_prefix + "livevqc.json",
    ]
    
    
    toks = ["good", "poor", "high", "low", "excellent", "bad", "fine", "moderate", "decent", "average", "medium", "acceptable"]
    print(toks)
    ids_ = [id_[1] for id_ in tokenizer(toks)["input_ids"]]
    print(ids_)
    

    for image_path, json_ in zip(image_paths, jsons):
        with open(json_) as f:
            iqadata = json.load(f)  

        for i, llddata in enumerate(tqdm(iqadata, desc="Evaluating [{}]".format(json_.split("/")[-1]))):
            #print(f"Evaluating image {i}")
            #print(prompt)
            filename = llddata["img_path"]
            llddata["logits"] = defaultdict(float)

            images = load_video(image_path + filename)
            num_frames = len(images)
            for image in images:
                image_tensor = image_processor.preprocess(image, return_tensors='pt')['pixel_values'].half().cuda()

                input_ids = tokenizer_image_token(prompt, tokenizer, IMAGE_TOKEN_INDEX, return_tensors='pt').unsqueeze(0).cuda()

                stop_str = conv.sep if conv.sep_style != SeparatorStyle.TWO else conv.sep2
                keywords = [stop_str]
                stopping_criteria = KeywordsStoppingCriteria(keywords, tokenizer, input_ids)

                with torch.inference_mode():
                    output_logits = model(input_ids,
                        images=image_tensor)["logits"][:,-1]

                for tok, id_ in zip(toks, ids_):
                    llddata["logits"][tok] += output_logits[0,id_].item()
                    
            for tok, id_ in zip(toks, ids_):
                llddata["logits"][tok] /= num_frames
            with open(f"results/mix-llava-v1.5-7b-boost/{json_.split('/')[-1]}", "a") as wf:
                json.dump(llddata, wf)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=str, default="teowu/llava_v1.5_7b_qinstruct_preview_v0.1")
    parser.add_argument("--model-base", type=str, default=None)
    parser.add_argument("--query", type=str, default="Rate the quality of the image.")
    parser.add_argument("--conv-mode", type=str, default="llava_v1")
    args = parser.parse_args()

    eval_model(args)
