# Changing the original script to covert the SODA-A lables to YOLO format


# Copyright (c) OpenMMLab. All rights reserved.
# Written by jbwang1997
# Reference: https://github.com/jbwang1997/BboxToolkit
# adopted from https://github.com/shaunyuan22/SODA-mmrotate/blob/main/tools/data/sodaa/sodaa_split.py


import argparse
import codecs
import datetime
import itertools
import json
import logging
import os
import os.path as osp
import time
from functools import partial, reduce
from math import ceil
from multiprocessing import Manager, Pool

import cv2
import numpy as np
from PIL import Image
import cv2
import copy

Image.MAX_IMAGE_PIXELS = None

try:
    import shapely.geometry as shgeo
except ImportError:
    shgeo = None

CLASSES = ['airplane', 'helicopter', 'small-vehicle', 'large-vehicle',
           'ship', 'container', 'storage-tank', 'swimming-pool',
           'windmill', 'ignore']

def add_parser(parser):
    """Add arguments."""
    parser.add_argument(
        '--base-json',
        type=str,
        default='./split_configs/sodaa_val.json',
        help='json config file for split images')
    parser.add_argument(
        '--nproc', type=int, default=10, help='the procession number')

    # argument for loading data
    parser.add_argument(
        '--img-dirs',
        nargs='+',
        type=str,
        default=None,
        help='images dirs, must give a value')
    parser.add_argument(
        '--ann-dirs',
        nargs='+',
        type=str,
        default=None,
        help='annotations dirs, optional')

    # argument for splitting image
    parser.add_argument(
        '--sizes',
        nargs='+',
        type=int,
        default=[800],
        help='the sizes of sliding windows')
    parser.add_argument(
        '--gaps',
        nargs='+',
        type=int,
        default=[650],  # 800 - 150
        help='the steps of sliding widnows')
    parser.add_argument(
        '--rates',
        nargs='+',
        type=float,
        default=[1.],
        help='same as DOTA devkit rate, but only change windows size')
    parser.add_argument(
        '--img-rate-thr',
        type=float,
        default=0.6,
        help='the minimal rate of image in window and window')
    parser.add_argument(
        '--iof-thr',
        type=float,
        default=0.7,
        help='the minimal iof between a object and a window')
    parser.add_argument(
        '--no-padding',
        action='store_true',
        help='not padding patches in regular size')
    parser.add_argument(
        '--padding-value',
        nargs='+',
        type=int,
        default=[0],
        help='padding value, 1 or channel number')

    # argument for saving
    parser.add_argument(
        '--save-dir',
        type=str,
        default='.',
        help='to save pkl and split images')
    parser.add_argument(
        '--save-ext',
        type=str,
        default='.png',
        help='the extension of saving images')


def parse_args():
    """Parse arguments."""
    parser = argparse.ArgumentParser(description='Splitting images')
    add_parser(parser)
    args = parser.parse_args()

    if args.base_json is not None:
        with open(args.base_json, 'r') as f:
            prior_config = json.load(f)

        for action in parser._actions:
            if action.dest not in prior_config or \
                    not hasattr(action, 'default'):
                continue
            action.default = prior_config[action.dest]
        args = parser.parse_args()

    # assert arguments
    assert args.img_dirs is not None, "argument img_dirs can't be None"
    assert args.ann_dirs is None or len(args.ann_dirs) == len(args.img_dirs)
    assert len(args.sizes) == len(args.gaps)
    assert len(args.sizes) == 1 or len(args.rates) == 1
    assert args.save_ext in ['.jpg']
    assert args.iof_thr >= 0 and args.iof_thr < 1
    assert args.iof_thr >= 0 and args.iof_thr <= 1
    assert not osp.exists(args.save_dir), \
        f'{osp.join(args.save_dir)} already exists'
    return args


def get_sliding_window(info, sizes, gaps, img_rate_thr):
    """Get sliding windows.

    Args:
        info (dict): Dict of image's width and height.
        sizes (list): List of window's sizes.
        gaps (list): List of window's gaps.
        img_rate_thr (float): Threshold of window area divided by image area.

    Returns:
        list[np.array]: Information of valid windows.
    """
    eps = 0.01
    windows = []
    width, height = info['width'], info['height']
    for size, gap in zip(sizes, gaps):
        assert size > gap, f'invaild size gap pair [{size} {gap}]'
        step = size - gap

        x_num = 1 if width <= size else ceil((width - size) / step + 1)
        x_start = [step * i for i in range(x_num)]
        if len(x_start) > 1 and x_start[-1] + size > width:
            x_start[-1] = width - size

        y_num = 1 if height <= size else ceil((height - size) / step + 1)
        y_start = [step * i for i in range(y_num)]
        if len(y_start) > 1 and y_start[-1] + size > height:
            y_start[-1] = height - size

        start = np.array(
            list(itertools.product(x_start, y_start)), dtype=np.int64)
        stop = start + size
        windows.append(np.concatenate([start, stop], axis=1))
    windows = np.concatenate(windows, axis=0)

    img_in_wins = windows.copy()
    img_in_wins[:, 0::2] = np.clip(img_in_wins[:, 0::2], 0, width)
    img_in_wins[:, 1::2] = np.clip(img_in_wins[:, 1::2], 0, height)
    img_areas = (img_in_wins[:, 2] - img_in_wins[:, 0]) * \
                (img_in_wins[:, 3] - img_in_wins[:, 1])
    win_areas = (windows[:, 2] - windows[:, 0]) * \
                (windows[:, 3] - windows[:, 1])
    img_rates = img_areas / win_areas
    if not (img_rates > img_rate_thr).any():
        max_rate = img_rates.max()
        img_rates[abs(img_rates - max_rate) < eps] = 1
    return windows[img_rates > img_rate_thr]


def poly2hbb(polys):
    """Convert polygons to horizontal polys.

    Args:
        polys (np.array): Polygons with shape (N, 8)

    Returns:
        np.array: Horizontal polys.
    """
    shape = polys.shape
    polys = polys.reshape(*shape[:-1], shape[-1] // 2, 2)
    lt_point = np.min(polys, axis=-2)
    rb_point = np.max(polys, axis=-2)
    return np.concatenate([lt_point, rb_point], axis=-1)


def bbox_overlaps_iof(polys1, polys2, eps=1e-6):
    """Compute bbox overlaps (iof).

    Args:
        polys1 (np.array): Horizontal polys1.
        polys2 (np.array): Horizontal polys2.
        eps (float, optional): Defaults to 1e-6.

    Returns:
        np.array: Overlaps.
    """
    rows = polys1.shape[0]
    cols = polys2.shape[0]

    if rows * cols == 0:
        return np.zeros((rows, cols), dtype=np.float32)

    hpolys1 = poly2hbb(polys1).reshape(-1, 4)
    hpolys2 = polys2
    try:
        hpolys1 = hpolys1[:, None, :]
    except IndexError:
        print()
    lt = np.maximum(hpolys1[..., :2], hpolys2[..., :2])
    rb = np.minimum(hpolys1[..., 2:], hpolys2[..., 2:])
    wh = np.clip(rb - lt, 0, np.inf)
    h_overlaps = wh[..., 0] * wh[..., 1]

    l, t, r, b = [polys2[..., i] for i in range(4)]
    polys2 = np.stack([l, t, r, t, r, b, l, b], axis=-1)
    if shgeo is None:
        raise ImportError('Please run "pip install shapely" '
                          'to install shapely first.')
    # the following lines were used to avoid single ann with a shape like (N, )
    polys1 = polys1.reshape(-1, 8)
    rows = polys1.shape[0]
    sg_polys1 = [shgeo.Polygon(p) for p in polys1.reshape(rows, -1, 2)]
    sg_polys2 = [shgeo.Polygon(p) for p in polys2.reshape(cols, -1, 2)]
    overlaps = np.zeros(h_overlaps.shape)
    for p in zip(*np.nonzero(h_overlaps)):
        overlaps[p] = sg_polys1[p[0]].intersection(sg_polys2[p[-1]]).area
    unions = np.array([p.area for p in sg_polys1], dtype=np.float32)
    unions = unions[..., None]

    unions = np.clip(unions, eps, np.inf)
    outputs = overlaps / unions
    if outputs.ndim == 1:
        outputs = outputs[..., None]
    return outputs


def get_window_obj(info, windows, iof_thr):
    """

    Args:
        info (dict): Dict of bbox annotations.
        windows (np.array): information of sliding windows.
        iof_thr (float): Threshold of overlaps between bbox and window.

    Returns:
        list[dict]: List of bbox annotations of every window.
    """
    polys = info['ann']['polys']
    iofs = bbox_overlaps_iof(polys, windows)

    window_anns = []
    for i in range(windows.shape[0]):
        win_iofs = iofs[:, i]
        pos_inds = np.nonzero(win_iofs >= iof_thr)[0].tolist()

        win_ann = dict()
        for k, v in info['ann'].items():
            if k == 'ign_polys':
                continue
            try:
                win_ann[k] = v[pos_inds]
            except TypeError:
                win_ann[k] = [v[i] for i in pos_inds]
        win_ann['trunc'] = win_iofs[pos_inds] < 1
        window_anns.append(win_ann)
    return window_anns


def crop_and_save_img(info, windows, window_anns, img_dir, no_padding,
                      padding_value, save_dir, anno_dir, img_ext):
    """

    Args:
        info (dict): Image's information.
        windows (np.array): information of sliding windows.
        window_anns (list[dict]): List of bbox annotations of every window.
        img_dir (str): Path of images.
        no_padding (bool): If True, no padding.
        padding_value (tuple[int|float]): Padding value.
        save_dir (str): Save filename.
        anno_dir (str): Annotation filename.
        img_ext (str): Picture suffix.

    Returns:
        list[dict]: Information of paths.
    """
    img = cv2.imread(osp.join(img_dir, info['filename']))
    img, info = fill_ign(img, info)
    patch_infos = []
    for i in range(windows.shape[0]):
        patch_info = dict()
        for k, v in info.items():
            if k not in ['id', 'fileanme', 'width', 'height', 'ann']:
                patch_info[k] = v

        window = windows[i]
        x_start, y_start, x_stop, y_stop = window.tolist()
        patch_info['x_start'] = x_start
        patch_info['y_start'] = y_start
        patch_info['id'] = \
            info['id'] + '__' + str(x_stop - x_start) + \
            '__' + str(x_start) + '___' + str(y_start)
        patch_info['ori_id'] = info['id']

        # TODO: polys have negative values!!! solution maybe: delete corresponding boxes
        ann = window_anns[i]
        ann['polys'] = translate(ann['polys'], -x_start, -y_start)
        patch_info['ann'] = ann

        patch = img[y_start:y_stop, x_start:x_stop]
        if not no_padding:
            height = y_stop - y_start
            width = x_stop - x_start
            if height > patch.shape[0] or width > patch.shape[1]:
                padding_patch = np.empty((height, width, patch.shape[-1]),
                                         dtype=np.uint8)
                if not isinstance(padding_value, (int, float)):
                    assert len(padding_value) == patch.shape[-1]
                padding_patch[...] = padding_value
                padding_patch[:patch.shape[0], :patch.shape[1], ...] = patch
                patch = padding_patch
        patch_info['height'] = patch.shape[0]
        patch_info['width'] = patch.shape[1]

        cv2.imwrite(osp.join(save_dir, patch_info['id'] + img_ext), patch)
        patch_info['filename'] = patch_info['id'] + img_ext
        patch_infos.append(patch_info)

        polys_num = patch_info['ann']['polys'].shape[0]
        outdir = os.path.join(anno_dir, patch_info['id'] + '.json')

        # categories
        categories = [
            dict(id=0, name='airplane'),
            dict(id=1, name='helicopter'),
            dict(id=2, name='small-vehicle'),
            dict(id=3, name='large-vehicle'),
            dict(id=4, name='ship'),
            dict(id=5, name='container'),
            dict(id=6, name='storage-tank'),
            dict(id=7, name='swimming-pool'),
            dict(id=8, name='windmill')
        ]
        # annotations
        annotations = [
            dict(poly=patch_info['ann']['polys'][i].tolist(),
                 cat_id=int(patch_info['ann']['cat_ids'][i]),
                 trunc=1 if patch_info['ann']['trunc'][i] else 0)
            for i in range(polys_num)
        ]
        patch_info.pop('ann')
        patch_info['annotations'] = annotations
        patch_info['categories'] = categories

        #json.dump(patch_info, open(outdir, 'w'), indent=4)
        
        #Change this part to convert the labels to YOLO format
        

        text_list = [f'''{int(patch_info['ann']['cat_ids'][i])} {int(patch_info["ann"]["polys"][i][0])/patch_info['width']} {int(patch_info["ann"]["polys"][i][1])/patch_info['height']}  
                                                        {int(patch_info["ann"]["polys"][i][2])/patch_info['width']} {int(patch_info["ann"]["polys"][i][3])/patch_info['height']}  
                                                        {int(patch_info["ann"]["polys"][i][4])/patch_info['width']} {int(patch_info["ann"]["polys"][i][7])/patch_info['height']}  
                                                        {int(patch_info["ann"]["polys"][i][6])/patch_info['width']} {int(patch_info["ann"]["polys"][i][7])/patch_info['height']}''' 
                for i in range(polys_num)
                ]
                
        
        
        txt_ann = outdir.replace('.json', '.txt')
        with codecs.open(txt_ann, 'w', 'utf-8') as f:
            for row in text_list:
                f.write(row + '\n')   

    return patch_infos


def fill_ign(img, info):
    """ Fill ignore regions of original image with 0, and return the masked image
        and filtered annotations. """
    ann = info['ann']
    polys = ann['polys']
    cat_ids = ann['cat_ids']
    ign_polys = ann['ign_polys']
    vld_polys = copy.deepcopy(polys).reshape(-1, 8)

    ign_mask = np.ones_like(img[:, :, 0])
    for ign_poly in ign_polys:
        ign_poly = np.array(ign_poly).astype(np.int32).reshape([-1, 2])
        cv2.fillPoly(ign_mask, [ign_poly], 0)
    for vld_poly in vld_polys:
        try:
            vld_poly = vld_poly.astype(np.int32).reshape([-1, 2])
        except ValueError:
            print()
        cv2.fillPoly(ign_mask, [vld_poly], 1)
    ign_mask = np.expand_dims(ign_mask, 2)  # (H, W, 1)
    img = img * ign_mask

    ann = dict(
        polys = polys,
        cat_ids = cat_ids
    )   # discard ign_polys
    info['ann'] = ann
    return img, info


def single_split(arguments, sizes, gaps, img_rate_thr, iof_thr, no_padding,
                 padding_value, save_dir, anno_dir, img_ext, lock, prog, total,
                 logger):
    """

    Args:
        arguments (object): Parameters.
        sizes (list): List of window's sizes.
        gaps (list): List of window's gaps.
        img_rate_thr (float): Threshold of window area divided by image area.
        iof_thr (float): Threshold of overlaps between bbox and window.
        no_padding (bool): If True, no padding.
        padding_value (tuple[int|float]): Padding value.
        save_dir (str): Save filename.
        anno_dir (str): Annotation filename.
        img_ext (str): Picture suffix.
        lock (object): Lock of Manager.
        prog (object): Progress of Manager.
        total (object): Length of infos.
        logger (object): Logger.

    Returns:
        list[dict]: Information of paths.
    """
    info, img_dir = arguments
    windows = get_sliding_window(info, sizes, gaps, img_rate_thr)
    window_anns = get_window_obj(info, windows, iof_thr)
    patch_infos = crop_and_save_img(info, windows, window_anns, img_dir,
                                    no_padding, padding_value, save_dir,
                                    anno_dir, img_ext)
    assert patch_infos

    lock.acquire()
    prog.value += 1
    msg = f'({prog.value / total:3.1%} {prog.value}:{total})'
    msg += ' - ' + f"Filename: {info['filename']}"
    msg += ' - ' + f"width: {info['width']:<5d}"
    msg += ' - ' + f"height: {info['height']:<5d}"
    msg += ' - ' + f"Objects: {len(info['ann']['polys']):<5d}"
    msg += ' - ' + f'Patches: {len(patch_infos)}'
    logger.info(msg)
    lock.release()

    return patch_infos


def setup_logger(log_path):
    """Setup logger.

    Args:
        log_path (str): Path of log.

    Returns:
        object: Logger.
    """
    logger = logging.getLogger('img split')
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = osp.join(log_path, now + '.log')
    handlers = [logging.StreamHandler(), logging.FileHandler(log_path, 'w')]

    for handler in handlers:
        handler.setFormatter(formatter)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def translate(polys, x, y):
    """Map polys from window coordinate back to original coordinate.

    Args:
        polys (np.array): polys with window coordinate.
        x (float): Deviation value of x-axis.
        y (float): Deviation value of y-axis

    Returns:
        np.array: polys with original coordinate.
    """
    dim = polys.shape[-1]
    translated = polys + np.array([x, y] * int(dim / 2), dtype=np.float32)
    if translated.any():
        t_max = np.max(translated)
        translated = np.clip(translated, 0, t_max)
    if translated.shape[0] > 0 and np.min(translated) < 0:
        print('anomaly poly: ', translated)
    return translated


def load_sodaa(img_dir, ann_dir=None, nproc=10):
    """Load SODA-A dataset.

    Args:
        img_dir (str): Path of images.
        ann_dir (str): Path of annotations.
        nproc (int): number of processes.

    Returns:
        list: Dataset's contents.
    """
    assert osp.isdir(img_dir), f'The {img_dir} is not an existing dir!'
    assert ann_dir is None or osp.isdir(
        ann_dir), f'The {ann_dir} is not an existing dir!'

    print('Starting loading SODA-A dataset information.')
    start_time = time.time()
    _load_func = partial(_load_sodaa_single, img_dir=img_dir, ann_dir=ann_dir)
    if nproc > 1:
        pool = Pool(nproc)
        contents = pool.map(_load_func, sorted(os.listdir(ann_dir)))
        pool.close()
    else:
        contents = list(map(_load_func, sorted(os.listdir(ann_dir))))
    contents = [c for c in contents if c is not None]
    end_time = time.time()
    print(f'Finishing loading SODA-A dataset, get {len(contents)} images,',
          f'using {end_time - start_time:.3f}s.')

    return contents


def _load_sodaa_single(annfile, img_dir, ann_dir):
    """Load DOTA's single image.

    Args:
        annfile (str): Filename of single annotation.
        img_dir (str): Path of images.
        ann_dir (str): Path of annotations.

    Returns:
        dict: Content of single image.
    """
    ann_id, ext = osp.splitext(annfile)
    if ext not in ['.json']:
        return None

    jsonfile = osp.join(ann_dir, annfile)
    imgpath = None if img_dir is None else osp.join(img_dir, ann_id + '.jpg')
    
    content = _load_sodaa_json(jsonfile)
    size = Image.open(imgpath).size
    

    content.update(
        dict(width=size[0], height=size[1], filename= ann_id + '.jpg', id=ann_id))
    return content


def _load_sodaa_json(jsonfile):
    """Load SODA-A's json annotation.

    Args:
        jsonfile (str): Path of annotation file with json format.

    Returns:
        dict: Annotation of single image.
    """
    polys, cat_ids, ign_polys = [], [], []
    if jsonfile is None:
        raise FileNotFoundError
    else:
        file = json.load(open(jsonfile, 'r'))
        anns = file['annotations']
        for ann in anns:
            cat_id = ann['category_id']  # 0-index
            if cat_id == 9: # ignore
                ign_polys.append(ann['poly'])
            else:
                poly = ann['poly']
                if len(poly) > 8:
                    continue    # neglect those annotations with more than 8-polygons
                # poly = np.array(poly, dtype=np.float32).reshape(-1, 8)
                polys.append(poly)
                cat_ids.append(cat_id)
    polys = np.array(polys, dtype=np.float32).squeeze() if polys else \
        np.zeros((0, 8), dtype=np.float32)
    cat_ids = np.array(cat_ids, dtype=np.float32) if cat_ids else \
        np.zeros((0,), dtype=np.int64)
    ann = dict(polys=polys, cat_ids=cat_ids, ign_polys=ign_polys)
    return dict(ann=ann)


def main():
    """Main function of image split."""
    args = parse_args()

    if args.ann_dirs is None:
        args.ann_dirs = [None for _ in range(len(args.img_dirs))]
    padding_value = args.padding_value[0] \
        if len(args.padding_value) == 1 else args.padding_value
    sizes, gaps = [], []
    for rate in args.rates:
        sizes += [int(size / rate) for size in args.sizes]
        gaps += [int(gap / rate) for gap in args.gaps]
    save_imgs = osp.join(args.save_dir, 'Images')
    save_files = osp.join(args.save_dir, 'Annotations')
    os.makedirs(save_imgs)
    os.makedirs(save_files)
    logger = setup_logger(args.save_dir)

    print('Loading original data!!!')
    infos, img_dirs = [], []
    for img_dir, ann_dir in zip(args.img_dirs, args.ann_dirs):
        _infos = load_sodaa(img_dir=img_dir, ann_dir=ann_dir, nproc=args.nproc)
        _img_dirs = [img_dir for _ in range(len(_infos))]
        infos.extend(_infos)
        img_dirs.extend(_img_dirs)

    print('Start splitting images!!!')
    start = time.time()
    manager = Manager()
    worker = partial(
        single_split,
        sizes=sizes,
        gaps=gaps,
        img_rate_thr=args.img_rate_thr,
        iof_thr=args.iof_thr,
        no_padding=args.no_padding,
        padding_value=padding_value,
        save_dir=save_imgs,
        anno_dir=save_files,
        img_ext=args.save_ext,
        lock=manager.Lock(),
        prog=manager.Value('i', 0),
        total=len(infos),
        logger=logger)

    if args.nproc > 1:
        pool = Pool(args.nproc)
        patch_infos = pool.map(worker, zip(infos, img_dirs))
        pool.close()
    else:
        patch_infos = list(map(worker, zip(infos, img_dirs)))

    patch_infos = reduce(lambda x, y: x + y, patch_infos)
    stop = time.time()
    print(f'Finish splitting images in {int(stop - start)} second!!!')
    print(f'Total images number: {len(patch_infos)}')


if __name__ == '__main__':
    main()
