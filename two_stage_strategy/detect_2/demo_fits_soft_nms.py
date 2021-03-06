# ------------------------------------------------------------------------------------------
# The pytorch demo code for detecting the object in a specific image (fpn specific version)
# Licensed under The MIT License [see LICENSE for details]
# Written by Jianwei Yang, modified by Zongxian Li, based on code from faster R-CNN
# ------------------------------------------------------------------------------------------

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
import pandas as pd
import _init_paths
from model.utils.blob import im_list_to_blob
import os
import sys
import numpy as np

np.set_printoptions(suppress=True)
import argparse
import pprint
import pdb
import time
import cv2
import matplotlib.pyplot as plt
import pickle as cPickle
import torch
from numpy.core.multiarray import ndarray
from torch.autograd import Variable
import torch.nn as nn
import torch.optim as optim
# from scipy.misc import imread
from imageio import imread
from roi_data_layer.roidb_v1 import combined_roidb
from roi_data_layer.roibatchLoader import roibatchLoader
from model.utils.config import cfg, cfg_from_file, cfg_from_list, get_output_dir
from model.rpn.bbox_transform import clip_boxes
from model.soft_nms.nms import soft_nms
from model.soft_nms.nms import nms
from model.rpn.bbox_transform import bbox_transform_inv
from model.utils.net_utils import vis_detections
# from model.fpn.fpn_cascade import _FPN
from model.fpn.resnet_IN import resnet
from astropy.io import fits
import pdb
import warnings
import glob

from scipy import ndimage
from photutils.aperture import CircularAperture, aperture_photometry
from skimage.transform import resize
warnings.filterwarnings('ignore')


def parse_args():
    """
    Parse input arguments
    """
    parser = argparse.ArgumentParser(description='Train a Fast R-CNN network')
    parser.add_argument('--webcam_num', dest='webcam_num',
                        help='webcam ID number',
                        default=-1, type=int)
    parser.add_argument('--dataset', dest='dataset',
                        help='training dataset',
                        default='EP_detect', type=str)
    parser.add_argument('--cfg', dest='cfg_file',
                        help='optional config file',
                        default='cfgs/res50.yml', type=str)
    parser.add_argument('--net', dest='net',
                        help='vgg16, res50, res101, res152',
                        default='res50', type=str)
    parser.add_argument('--set', dest='set_cfgs',
                        help='set config keys', default=None,
                        nargs=argparse.REMAINDER)
    parser.add_argument('--load_dir', dest='load_dir',
                        help='directory to load models',
                        default="./model_save",
                        nargs=argparse.REMAINDER)                        # ??????
    parser.add_argument('--cuda', dest='cuda',
                        help='whether use CUDA', default=1,
                        action='store_true')
    parser.add_argument('--image_dir', dest='image_dir',
                        help='directory to load images for demo',
                        default="./validation")  # ??????
    parser.add_argument('--cag', dest='class_agnostic',
                        help='whether perform class_agnostic bbox regression',
                        action='store_true')
    parser.add_argument('--parallel_type', dest='parallel_type',
                        help='which part of model to parallel, 0: all, 1: model before roi pooling',
                        default=0, type=int)
    parser.add_argument('--checksession', dest='checksession',
                        help='checksession to load model',
                        default=121, type=int)                  # 1  121  52
    parser.add_argument('--checkepoch', dest='checkepoch',
                        help='checkepoch to load network',
                        default=13, type=int)                   # 46  13  26
    parser.add_argument('--checkpoint', dest='checkpoint',
                        help='checkpoint to load network',
                        default=229, type=int)                 # 90  229  95
    parser.add_argument('--bs', dest='batch_size',
                        help='batch_size',
                        default=1, type=int)
    parser.add_argument('--lr', dest='lr',
                        help='starting learning rate',
                        default=0.001, type=float)

    ###  begin to test
    parser.add_argument('--thresh', dest='thresh',
                        help='thresh to select scores',
                        default=0.95, type=float)           # ??????????????? can alter
    parser.add_argument('--vis', dest='vis',
                        help='visualization mode',
                        default=True,
                        action='store_true')
    args = parser.parse_args()
    return args


def _get_image_blob(im):
    """Converts an image into a network input.
    Arguments:
      im (ndarray): a color image in BGR order
    Returns:
      blob (ndarray): a data blob holding an image pyramid
      im_scale_factors (list): list of image scales (relative to im) used
        in the image pyramid
    """
    im_orig = im.astype(np.float32, copy=True)
    im_shape = im_orig.shape
    im_size_min = np.min(im_shape[0:2])
    im_size_max = np.max(im_shape[0:2])

    processed_ims = []
    im_scale_factors = []

    for target_size in cfg.TEST.SCALES:
        im_scale = float(target_size) / float(im_size_min)
        # Prevent the biggest axis from being more than MAX_SIZE
        if np.round(im_scale * im_size_max) > cfg.TEST.MAX_SIZE:
            im_scale = float(cfg.TEST.MAX_SIZE) / float(im_size_max)
        im = cv2.resize(im_orig, None, None, fx=im_scale, fy=im_scale,
                        interpolation=cv2.INTER_LINEAR)
        im_scale_factors.append(im_scale)
        processed_ims.append(im)

    # Create a blob to hold the input images
    blob = im_list_to_blob(processed_ims)

    return blob, np.array(im_scale_factors)


# calculate pression and recall
def cal_indicators(save_path, det, flux_internal):
    file_name = save_path.split("/")[-1].split("_")[0]
    csv_file = "../obsinfo/obsinfo" + file_name + '.csv'
    cmos = int(save_path.split("/")[-1].split(".")[0].split("_")[-1])
    df_label = pd.read_csv(csv_file)
    df_label_1 = df_label[(df_label['cmosnum'] == cmos)]  # .index.tolist()  # coms????????????int
    df_label_1_x = df_label_1['x'].tolist()
    df_label_1_y = df_label_1['y'].tolist()
    df_label_1_flux = df_label_1['flux/mCrab'].tolist()
    n_real = len(df_label_1_y)
    n_se_num = len(flux_internal)
    recall_internal_num = np.zeros(n_se_num)
    sensitivity_internal_num = np.zeros(n_se_num)
    true_num = 0
    precision_num = len(det)
    flag = np.zeros(n_real)
    file = open(save_path, 'w+')
    for t in range(precision_num):
        xm1, xm2 = (det[t, 0] * 8 + 1), (det[t, 2] * 8 + 1)
        ym1, ym2 = (det[t, 1] * 8 + 1), (det[t, 3] * 8 + 1)
        for i in range(n_real):
            if not flag[i]:  # ????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
                y0, x0 = df_label_1_y[i], df_label_1_x[i]  # ?????????????????????
                if xm1 <= x0 <= xm2 and ym1 <= y0 <= ym2:
                    flag[i] = 1
                    # ?????????????????????
                    file.write("location {}(x,y):{:.4f} {:.4f}\n".format(i + 1, (xm1 + xm2) / 2, (ym1 + ym2) / 2))
                    true_num += 1
                    if df_label_1_flux[i] >= flux_internal[-1]:
                        recall_internal_num[-1] += 1
                    else:
                        for j in range(n_se_num - 1):
                            if df_label_1_flux[i] >= flux_internal[j] and df_label_1_flux[i] < flux_internal[j + 1]:
                                recall_internal_num[j] += 1
                    break  # ??????????????????????????????????????????????????????????????????????????????????????????SOFT-NMS??????????????????????????????????????????

    # ????????????\??????(???????????????)\?????????
    if not true_num:
        file.write("no detected object???\n")
        print("There is no detected object in the %d image of %s ???\n" % (cmos, file_name))
    for j in range(n_se_num - 1):
        sensitivity_internal_num[j] = len(list(
            filter(lambda t: t >= flux_internal[j] and t < flux_internal[j + 1],
                   df_label_1_flux)))  # ????????????sensitivity????????????
    sensitivity_internal_num[-1] = len(
        list(filter(lambda t: t >= flux_internal[-1], df_label_1_flux)))  # ????????????sensitivity????????????

    file.close()

    return true_num, recall_internal_num, precision_num, sensitivity_internal_num



def possible_target_points(img_mat, x_y_w_h):
    # all_point_x = []  # ???????????????????????????????????????
    # all_point_y = []
    i_x_y_w_h = []  # ??????????????????????????????????????????????????????x???
    n1 = 512
    min_scale = 0.5
    min_corrcoef = 0.12
    psf_matrix = np.load('../psf_matrix_512.npy')
    # ?????????????????????
    kernel_5 = resize(psf_matrix, (5, 5), anti_aliasing=True)
    psf_col = kernel_5.reshape(kernel_5.size, order='C')
    for i in range(len(x_y_w_h)):
        x1 = x_y_w_h[i][0]
        y1 = x_y_w_h[i][1]
        x2 = x_y_w_h[i][2]
        y2 = x_y_w_h[i][3]
        try:
            small_m = resize(img_mat[max(0, int(y1)):min(n1, int(y2)),
                      max(0, int(x1)):min(n1, int(x2))], (5, 5))          # ????????????resize???5*5??????
            small_m_col = small_m.reshape(small_m.size, order='C')
            corrcoef = abs(np.corrcoef(small_m_col, psf_col)[0, 1])
            # # ????????????????????????????????????
            # small_m = img_mat[max(0, y0 - bia):min(n1, y0 + bia + 1),
            #           max(0, x0 - bia):min(n1, x0 + bia + 1)]  # ????????????????????????????????????(???????????????)
            real_i_num = 0  # ??????
            i_num = 0
            for j in range(len(small_m)):
                for t in range(len(small_m[0])):
                    # 5*5????????????
                    i_num += small_m[j][t]
                    # ????????????????????????
                    if abs(j - 2) == 0 or abs(t - 2) == 0:
                        real_i_num += small_m[j][t]  # or 1
        except ValueError:
            print(x_y_w_h)
        # min_scale = 0.80   # ??????????????????????????????????????????????????????????????????????????????????????????????????????
        # ???????????????????????????????????????????????????min_scale
        if i_num > 0 and corrcoef >= min_corrcoef and (real_i_num/i_num) >= min_scale:
            i_x_y_w_h.append(x_y_w_h[i])
    return i_x_y_w_h

def getAperturePhotometry(img, h_size, w_size):
    positions = [(float(w_size), float(h_size))]
    radii = 3   # ????????????:2.2
    aperture = CircularAperture(positions, r=radii)
    phot_table = aperture_photometry(img, aperture, method='exact')
    for col in phot_table.colnames:
        phot_table[col].info.format = '%.8g'  # for consistent table output
    result = phot_table[0][3]
    # result = str(phot_table[0]).split(' ')[-13]
    return result


def check_detections(im, x1_y1_x2_y2):
    """Visual debugging of detections.
    ??????????????????img?????????
    ?????????????????????x???y??????????????????????????????
    ?????????????????????x+w???y+h??????????????????????????????
    ?????????????????????0,255,0?????????????????????rgb??????
    ??????????????????2????????????????????????
    """
    im2show = (np.log(im + 1))
    max_f = np.max(im2show)  # ???????????????
    i_x_y_w_h = []  # ??????????????????????????????????????????????????????x???
    photometry_value_list = []
    bbox_list = []
    size = im.shape[0]
    n = len(x1_y1_x2_y2)
    for i in range(n):
        # x1 = np.around(x_y_w_h[i][0] - padding)
        # x2 = np.around(x_y_w_h[i][0] + padding+1)
        # y1 = np.around(x_y_w_h[i][1] - padding)
        # y2 = np.around(x_y_w_h[i][1] + padding+1)
        # x1 = max(int(x1), 0)
        # x2 = min(int(x2), size)
        # y1 = max(int(y1), 0)
        # y2 = min(int(y2), size)
        x1 = np.around(x1_y1_x2_y2[i][0])
        x2 = np.around(x1_y1_x2_y2[i][2])
        y1 = np.around(x1_y1_x2_y2[i][1])
        y2 = np.around(x1_y1_x2_y2[i][3])
        x1 = max(int(x1), 0)
        x2 = min(int(x2), size)
        y1 = max(int(y1), 0)
        y2 = min(int(y2), size)
        bbox_list.append((x1, y1, x2, y2))
        # aperturePhotometry
        # img_small = im[:, :, 0]
        # img = img_small[x1:x2, y1:y2]
        img = im[y1:y2, x1:x2]
        # cv2.imshow("star",img)
        # cv2.waitKey()
        # cv2.destroyAllWindows()
        h_size = (y2-y1)/2
        w_size = (x2-x1)/2
        photometry_value = getAperturePhotometry(img, h_size, w_size)
        photometry_value_list.append(photometry_value)

    # ?????????????????????
    photometry_value_t = 14
    for j in range(n):
        if photometry_value_list[j] > photometry_value_t:
            cv2.rectangle(im2show, bbox_list[j][0:2], bbox_list[j][2:4], max_f, 1)
            i_x_y_w_h.append(x1_y1_x2_y2[j])
    return im2show, i_x_y_w_h

if __name__ == '__main__':

    os.environ["CUDA_VISIBLE_DEVICES"] = "1"
    print("GPU {} will be used\n".format("0"))

    args = parse_args()

    lr = args.lr
    momentum = cfg.TRAIN.MOMENTUM
    weight_decay = cfg.TRAIN.WEIGHT_DECAY

    print('Called with args:')
    print(args)
    cfg.USE_GPU_NMS = args.cuda
    if args.cfg_file is not None:
        cfg_from_file(args.cfg_file)
    if args.set_cfgs is not None:
        cfg_from_list(args.set_cfgs)

    print('Using config:')
    pprint.pprint(cfg)
    # ?????????????????????
    # ????????????????????????????????????seed??????????????????????????????????????????
    # ???????????????seed?????????????????????????????????????????????
    np.random.seed(cfg.RNG_SEED)

    # load_dir ????????????   args.net ??????   args.dataset ?????????
    input_dir = args.load_dir + "/" + args.net + "/" + args.dataset
    if not os.path.exists(input_dir):
        raise Exception('There is no input directory for loading network from ' + input_dir)
    load_name = os.path.join(input_dir,
                             'fpn_{}_{}_{}.pth'.format(args.checksession, args.checkepoch, args.checkpoint))
    print(load_name)

    pascal_classes = np.asarray(['__background__', 'EP'])
    # initilize the network here.
    # class-agnostic ???????????????2???bounding box?????????????????????
    if args.net == 'res101':
        fpn = resnet(pascal_classes, 101, pretrained=False, class_agnostic=args.class_agnostic)
    elif args.net == 'res50':
        fpn = resnet(pascal_classes, 50, pretrained=False, class_agnostic=args.class_agnostic)
    elif args.net == 'res152':
        fpn = resnet(pascal_classes, 152, pretrained=False, class_agnostic=args.class_agnostic)
    else:
        print("network is not defined")
        # ??????pdb.set_trace()??????????????????????????????????????????????????????(Pdb)???
        pdb.set_trace()

    fpn.create_architecture()
    fpn.cuda()
    print("load checkpoint %s" % (load_name))
    if args.cuda > 0:
        checkpoint = torch.load(load_name)
    fpn.load_state_dict(checkpoint['model'])
    if 'pooling_mode' in checkpoint.keys():
        cfg.POOLING_MODE = checkpoint['pooling_mode']

    print('load model successfully!')

    im_data = torch.FloatTensor(1)
    im_info = torch.FloatTensor(1)
    num_boxes = torch.LongTensor(1)
    gt_boxes = torch.FloatTensor(1)
    # ship to cuda
    if args.cuda > 0:
        im_data = im_data.cuda()
        im_info = im_info.cuda()
        num_boxes = num_boxes.cuda()
        gt_boxes = gt_boxes.cuda()

    # make variable
    im_data = Variable(im_data)
    im_info = Variable(im_info)
    num_boxes = Variable(num_boxes)
    gt_boxes = Variable(gt_boxes)

    if args.cuda > 0:
        cfg.CUDA = True

    if args.cuda > 0:
        fpn.cuda()

    # ???dropout???batch normalization???????????????????????????????????????????????????
    # pytorch????????????BN???DropOut??????????????????????????????????????????????????????
    fpn.eval()

    start = time.time()
    psf_matrix = np.load('../psf_matrix_512.npy')

    fits_list = os.path.join(args.image_dir, '*.fits')
    imglist = glob.glob(fits_list)

    num_images = len(imglist)

    print('Loaded Photo: {} images.'.format(num_images))

    flux_interval = np.linspace(0, 1, 2)
    all_recall = np.zeros(len(flux_interval))
    all_flux_internal_num = np.zeros(len(flux_interval))
    precision_all = 0
    all_ture_num = 0
    while (num_images >= 0):
        box_list = list()
        total_tic = time.time()
        num_images -= 1


        # Load the demo image
        im_file = os.path.join(args.image_dir, imglist[num_images])
        img_fits = fits.open(im_file, ignore_missing_end=True)[0].data
        kernel = resize(psf_matrix, (5, 5))
        img = ndimage.convolve(img_fits, kernel / np.max(kernel))
        # ### use log transpoze
        # im = np.log(1 + np.abs(im))
        max_value = np.max(img)
        min_value = np.min(img)
        mean_value = np.mean(img)
        var_value = np.var(img)
        im_in = (img - mean_value) / (max_value - min_value)
        # im_in = (im - mean_value)/var_value

        if len(im_in.shape) == 2:
            im_in = im_in[:, :, np.newaxis]
            im_in = np.concatenate((im_in, im_in, im_in), axis=2)  # ?????????????????????
        # rgb -> bgr
        # line[:-1]??????????????????????????????????????????????????????????????????????????????????????????
        # line[::-1]?????????????????? line = "abcde" line[::-1] ????????????'edcba'
        im = im_in[:, :, ::-1]

        blobs, im_scales = _get_image_blob(im)  ##???????????? ?????????????????????????????????????????????????????? ?????????
        assert len(im_scales) == 1, "Only single-image batch implemented"
        im_blob = blobs
        im_info_np = np.array([[im_blob.shape[1], im_blob.shape[2], im_scales[0]]], dtype=np.float32)

        im_data_pt = torch.from_numpy(im_blob)
        im_data_pt = im_data_pt.permute(0, 3, 1, 2)
        im_info_pt = torch.from_numpy(im_info_np)

        # ???tensor????????????????????????????????????
        # ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        im_data.resize_(im_data_pt.size()).copy_(im_data_pt)
        # print(im_data.shape)
        im_info.resize_(im_info_pt.size()).copy_(im_info_pt)
        # print(im_info.shape)
        gt_boxes.resize_(1, 5).zero_()
        # print(gt_boxes.shape)
        num_boxes.resize_(1).zero_()
        # print(num_boxes.shape)

        # pdb.set_trace()
        det_tic = time.time()

        rois, cls_prob, bbox_pred, \
        _, _, _, _, _ = fpn(im_data, im_info, gt_boxes, num_boxes)

        scores = cls_prob.data
        boxes = rois.data[:, :, 1:5]

        if cfg.TEST.BBOX_REG:
            # Apply bounding-box regression deltas
            box_deltas = bbox_pred.data
            if cfg.TRAIN.BBOX_NORMALIZE_TARGETS_PRECOMPUTED:
                # Optionally normalize targets by a precomputed mean and stdev
                if args.class_agnostic:
                    if args.cuda > 0:
                        box_deltas = box_deltas.view(-1, 4) * torch.FloatTensor(cfg.TRAIN.BBOX_NORMALIZE_STDS).cuda() \
                                     + torch.FloatTensor(cfg.TRAIN.BBOX_NORMALIZE_MEANS).cuda()
                    else:
                        box_deltas = box_deltas.view(-1, 4) * torch.FloatTensor(cfg.TRAIN.BBOX_NORMALIZE_STDS) \
                                     + torch.FloatTensor(cfg.TRAIN.BBOX_NORMALIZE_MEANS)

                    box_deltas = box_deltas.view(1, -1, 4)
                else:
                    if args.cuda > 0:
                        box_deltas = box_deltas.view(-1, 4) * torch.FloatTensor(cfg.TRAIN.BBOX_NORMALIZE_STDS).cuda() \
                                     + torch.FloatTensor(cfg.TRAIN.BBOX_NORMALIZE_MEANS).cuda()
                    else:
                        box_deltas = box_deltas.view(-1, 4) * torch.FloatTensor(cfg.TRAIN.BBOX_NORMALIZE_STDS) \
                                     + torch.FloatTensor(cfg.TRAIN.BBOX_NORMALIZE_MEANS)
                    box_deltas = box_deltas.view(1, -1, 4 * len(pascal_classes))

            # model.rpn.bbox_transform ??????anchor??????????????????proposals
            # ????????????????????????????????????????????????[x1,y1,x2,y2]???
            pred_boxes = bbox_transform_inv(boxes, box_deltas, 1)
            # ?????????????????????????????????????????????????????????????????????,???????????????????????????
            pred_boxes = clip_boxes(pred_boxes, im_info.data, 1)
        else:
            # Simply repeat the boxes, once for each class
            # #Numpy??? tile() ??????,????????????????????????????????????????????????????????????
            pred_boxes = np.tile(boxes, (1, scores.shape[1]))

        pred_boxes /= im_scales[0]

        scores = scores.squeeze()
        pred_boxes = pred_boxes.squeeze()
        det_toc = time.time()
        detect_time = det_toc - det_tic
        misc_tic = time.time()

        # if vis:
        #     # jpg_name = os.path.join(args.image_dir, im_file.split("/")[-1].split(".fits")[0] + ".jpg")
        #     # im_jpg = cv2.imread(jpg_name)
        #     # im_jpg = cv2.flip(im_jpg,0)
        #     im2show = (np.log(img_fits+1))

        for j in range(1, len(pascal_classes)):  # ?????????????????????????????????
            inds = torch.nonzero(scores[:, j] > args.thresh).view(-1)  # ????????????0?????????
            # if there is det
            if inds.numel() > 0:
                cls_scores = scores[:, j][inds]
                _, order = torch.sort(cls_scores, 0, True)
                if args.class_agnostic:
                    cls_boxes = pred_boxes[inds, :]
                else:
                    cls_boxes = pred_boxes[inds][:, j * 4:(j + 1) * 4]

                cls_dets = torch.cat((cls_boxes, cls_scores.unsqueeze(1)), 1)
                # cls_dets = torch.cat((cls_boxes, cls_scores), 1)
                cls_dets = cls_dets[order]
                keep = nms(cls_dets, 0.3)
                # keep = soft_nms(cls_dets)  ##???use soft_nms or nms  ???????????????????????????cpu_nms()
                # keep = nms(cls_dets, cfg.TEST.NMS)
                ###  error : data type not understood
                # cls_dets = cls_dets([keep.view(-1).long()])
                cls_dets = keep

                if pascal_classes[j] == "EP":  # ??????
                    class_name_index = 100
                    class_name_column = [class_name_index] * cls_dets.shape[0]
                    class_name = np.array(class_name_column).reshape(len(class_name_column), 1)
                    cls_dets = np.concatenate([cls_dets], axis=1)

                box_list.append(cls_dets)
                # if vis:
                #     im2show, save_mat = vis_detections(im2show, pascal_classes[j], cls_dets,
                #                                        0.8)  # ??????NMS???????????????????????????????????????-????????????
        result_save_path = im_file[num_images][:-4].rstrip(".") + ".save.txt"
        result_path = im_file[num_images][:-4].rstrip(".") + "_det.txt"
        if not box_list:
            np.savetxt(result_path, np.array([-1]), fmt="%.8f")  # ???????????????????????????-1
        else:
            box_np = np.concatenate(box_list, axis=0)  # ????????????????????????????????????box_list
            # save_mat = np.array(save_mat)  # ????????????????????????????????????box_list
            x1_y1_x2_y2 = possible_target_points(img_fits, box_np)
            # ?????????+??????
            im2show, i_x1_y1_x2_y2_p = check_detections(img_fits, x1_y1_x2_y2)
            if i_x1_y1_x2_y2_p:
                x1_y1_x2_y2_np = np.array(i_x1_y1_x2_y2_p)  # ????????????????????????????????????box_list
                np.savetxt(result_path, x1_y1_x2_y2_np, fmt="%.8f")
                # ?????????????????????????????????????????????????????????flux???????????????????????????????????????????????????????????????flux????????????????????????????????????
                true_num, recall_internal_num, precision_num, flux_internal_num = cal_indicators(result_save_path, x1_y1_x2_y2_np,
                                                                                                 flux_interval)
                all_ture_num += true_num  # ????????????????????????????????????????????????????????????
                all_recall += recall_internal_num  # ?????????????????????flux???????????????????????????????????????????????????
                all_flux_internal_num += flux_internal_num  # ??????flux????????????????????????????????????
                precision_all += precision_num  # ??????????????????????????????

                if args.vis and args.webcam_num == -1:
                    result_path_plt = im_file[num_images][:-4] + "_detection.jpg"
                    plt.figure()
                    plt.imshow(np.log(im2show / np.max(im2show) + 9) * 255)
                    plt.savefig(result_path_plt)

        misc_toc = time.time()
        nms_time = misc_toc - misc_tic

    # ???????????????
    try:
        recall = all_recall / all_flux_internal_num  # ????????????????????????
    except ZeroDivisionError:
        print("???????????????0??????????????????????????????")
        recall = np.ones(len(flux_interval))  # ?????????
        for j in range(len(flux_interval)):
            if not all_flux_internal_num[j]:
                recall[j] = all_recall[j] / all_flux_internal_num[j]
    precision = all_ture_num / precision_all
    print('session{}_{}_indicators: \n recall = {}\n precision = {:.2f}'.format(
        args.checksession, args.thresh, recall, precision))
    # ????????????
    # plt.figure(figsize=(12, 12))
    # bar_width = 0.5
    bar_width = 1
    plt.bar(flux_interval, recall, bar_width, align='edge', color='r')  # align='center '
    plt.xlabel('flux_interval')
    plt.ylabel('recall')
    # plt.plot(flux_interval, recall, color="red", label="recall-img")
    # plt.legend(loc='best')
    plt.title('indicators_img')
    plt.savefig(
        './output/visiual_map_loss/session{}_{}_indicators_img.jpg'
            .format(args.checksession, args.thresh))
    plt.close()

    print("completed!!!")