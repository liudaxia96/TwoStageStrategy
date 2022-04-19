import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
import numpy as np
import scipy
import colorsys
import random
import torchvision.models as models
from model.utils.config import cfg
# from model.roi_crop.functions.roi_crop import RoICropFunction
import cv2
import pdb

def save_net(fname, net):
    import h5py
    h5f = h5py.File(fname, mode='w')
    for k, v in net.state_dict().items():
        h5f.create_dataset(k, data=v.cpu().numpy())

def load_net(fname, net):
    import h5py
    h5f = h5py.File(fname, mode='r')
    for k, v in net.state_dict().items():
        param = torch.from_numpy(np.asarray(h5f[k]))
        v.copy_(param)

def weights_normal_init(model, dev=0.01):
    if isinstance(model, list):
        for m in model:
            weights_normal_init(m, dev)
    else:
        for m in model.modules():
            if isinstance(m, nn.Conv2d):
                m.weight.data.normal_(0.0, dev)
            elif isinstance(m, nn.Linear):
                m.weight.data.normal_(0.0, dev)


def clip_gradient(model, clip_norm):
    """Computes a gradient clipping coefficient based on gradient norm."""
    totalnorm = 0
    for p in model.parameters():
        if p.requires_grad:
            modulenorm = p.grad.data.norm()
            totalnorm += modulenorm ** 2
    totalnorm = np.sqrt(totalnorm)

    norm = clip_norm / max(totalnorm, clip_norm)
    for p in model.parameters():
        if p.requires_grad:
            p.grad.mul_(norm)

def vis_detections_img(im, class_name, dets, thresh=0.8):
    """Visual debugging of detections.
    第一个参数：img是原图
    第二个参数：（x，y）是矩阵的左上点坐标
    第三个参数：（x+w，y+h）是矩阵的右下点坐标
    第四个参数：（0,255,0）是画线对应的rgb颜色
    第五个参数：2是所画的线的宽度
    """
    # for i in range(np.minimum(10, dets.shape[0])):
    all = []
    for i in range(dets.shape[0]):
        bbox = tuple(int(np.round(x)) for x in dets[i, :4])
        score = dets[i, -1]
        if score > thresh:
            if class_name == "EP":    # 修改
                cv2.rectangle(im, bbox[0:2], bbox[2:4], (0, 204, 0), 1)
                # cv2.putText(im, '%s: %.3f' % (class_name, score), (bbox[0], bbox[1] + 15), cv2.FONT_HERSHEY_PLAIN,
                #                 #             1.0, (0, 204, 0), thickness=1)
                all.append(dets[i])
            else:
                cv2.rectangle(im, bbox[0:2], bbox[2:4], (0, 0, 255), 1)
                # cv2.putText(im, '%s: %.3f' % (class_name, score), (bbox[0], bbox[1] + 15), cv2.FONT_HERSHEY_PLAIN,
                #             1.0, (0, 0, 255), thickness=1)
    return im,all

def vis_detections_new(im, dets, scale):
    """Visual debugging of detections.
    第一个参数：img是原图
    第二个参数：（x，y）是矩阵的左上点坐标
    第三个参数：（x+w，y+h）是矩阵的右下点坐标
    第四个参数：（0,255,0）是画线对应的rgb颜色
    第五个参数：2是所画的线的宽度
    """
    n = 4096//scale
    for i in range(dets.shape[0]):
        bbox = np.array(list(np.round(np.array(x)/scale) for x in dets[i, :4]))   # np.round(x):方法返回浮点数x的四舍五入值
        x1 = max(int(bbox[0:1]-bbox[2:3]/2), 0)
        y1 = max(int(bbox[1:2]-bbox[3:]/2), 0)
        x2 = min(int(bbox[0:1]+bbox[2:3]/2), n-1)
        y2 = min(int(bbox[1:2]+bbox[3:]/2), n-1)
        cv2.rectangle(im, (x1, y1), (x2, y2), np.max(im), 1)
    return im

def vis_detections(im, class_name, dets, thresh=0.8):
    """Visual debugging of detections.
    第一个参数：img是原图
    第二个参数：（x，y）是矩阵的左上点坐标
    第三个参数：（x+w，y+h）是矩阵的右下点坐标
    第四个参数：（0,255,0）是画线对应的rgb颜色
    第五个参数：2是所画的线的宽度
    """
    # for i in range(np.minimum(10, dets.shape[0])):
    # all = []
    for i in range(dets.shape[0]):
        bbox = tuple(int(np.round(x)) for x in dets[i, :4])
        score = dets[i, -1]
        if score > thresh:
            if class_name == "EP":    # 修改
                # cv2.rectangle(im, bbox[0:2], bbox[2:4], (0, 204, 0), 1)
                cv2.rectangle(im, bbox[0:2], bbox[2:4], np.max(im), 1)
                # cv2.putText(im, '%s: %.3f' % (class_name, score), (bbox[0], bbox[1] + 15), cv2.FONT_HERSHEY_PLAIN,
                #                 #             1.0, (0, 204, 0), thickness=1)
                # all.append(dets[i])
            else:
                # cv2.rectangle(im, bbox[0:2], bbox[2:4], (0, 0, 255), 1)
                cv2.rectangle(im, bbox[0:2], bbox[2:4], np.max(im), 1)
                # cv2.putText(im, '%s: %.3f' % (class_name, score), (bbox[0], bbox[1] + 15), cv2.FONT_HERSHEY_PLAIN,
                #             1.0, (0, 0, 255), thickness=1)
    return im

# Borrow from matterport mask R-CNN implementation
def unmold_mask(mask, bbox, image_shape):
    """Converts a mask generated by the neural network into a format similar
    to it's original shape.
    mask: [height, width] of type float. A small, typically 28x28 mask.
    bbox: [y1, x1, y2, x2]. The box to fit the mask in.
    Returns a binary mask with the same size as the original image.
    """
    threshold = 0.1
    x1, y1, x2, y2 = bbox
    if x2 == x1 or y2==y1:
        return np.zeros(image_shape[:2], dtype=np.uint8)
        
    mask = scipy.misc.imresize(
        mask, (y2 - y1, x2 - x1), interp='bilinear').astype(np.float32) / 255.0
    mask = np.where(mask >= threshold, 1, 0).astype(np.uint8)

    # Put the mask in the right location.
    full_mask = np.zeros(image_shape[:2], dtype=np.uint8)
    full_mask[y1:y2, x1:x2] = mask
    return full_mask

# Borrowed from matterport mask R-CNN implementation

def apply_mask(image, mask, nomask, color, alpha=0.5):
    """Apply the given mask to the image.
    """
    mask[nomask != 0] = 0
    for c in range(3):
        image[:, :, c] = np.where(mask == 1,
                                  image[:, :, c] *
                                  (1 - alpha) + alpha * color[c] * 255,
                                  image[:, :, c])
    return image


def random_colors(N, bright=True):

    """
    Generate random colors.
    To get visually distinct colors, generate them in HSV space then
    convert to RGB.
    """
    brightness = 1.0 if bright else 0.7
    hsv = np.random.rand(N, 3)
    hsv[:, 1] = 1
    hsv[:, 2] = brightness
    # hsv = [(i / N, 1, brightness) for i in range(N)]
    colors = list(map(lambda c: colorsys.hsv_to_rgb(*c), hsv))
    random.shuffle(colors)
    return colors

def vis_det_and_mask(im, class_name, dets, masks, thresh=0.8):
    """Visual debugging of detections."""
    num_dets = np.minimum(10, dets.shape[0])
    colors_mask = random_colors(num_dets)
    colors_bbox = np.round(np.random.rand(num_dets, 3) * 255)
    # sort rois according to the coordinates, draw upper bbox first
    draw_mask = np.zeros(im.shape[:2], dtype=np.uint8)

    for i in range(1):
        bbox = tuple(int(np.round(x)) for x in dets[i, :4])
        mask = masks[i, :, :]
        full_mask = unmold_mask(mask, bbox, im.shape)

        score = dets[i, -1]
        if score > thresh:
            word_width = len(class_name)
            cv2.rectangle(im, bbox[0:2], bbox[2:4], colors_bbox[i], 2)
            cv2.rectangle(im, bbox[0:2], (bbox[0] + 18 + word_width*8, bbox[1]+15), colors_bbox[i], thickness=cv2.FILLED)
            apply_mask(im, full_mask, draw_mask, colors_mask[i], 0.5)
            draw_mask += full_mask
            cv2.putText(im, '%s' % (class_name), (bbox[0]+5, bbox[1] + 12), cv2.FONT_HERSHEY_PLAIN,
								1.0, (255,255,255), thickness=1)
    return im


def adjust_learning_rate(optimizer, decay=0.1):
    """Sets the learning rate to the initial LR decayed by 0.5 every 20 epochs"""
    for param_group in optimizer.param_groups:
        param_group['lr'] = decay * param_group['lr']


def save_checkpoint(state, filename):
    torch.save(state, filename)

def _smooth_l1_loss(bbox_pred, bbox_targets, bbox_inside_weights, bbox_outside_weights, sigma=1.0, dim=[1]):

    sigma_2 = sigma ** 2
    box_diff = bbox_pred - bbox_targets
    in_box_diff = bbox_inside_weights * box_diff
    abs_in_box_diff = torch.abs(in_box_diff)
    smoothL1_sign = (abs_in_box_diff < 1. / sigma_2).detach().float()
    in_loss_box = torch.pow(in_box_diff, 2) * (sigma_2 / 2.) * smoothL1_sign \
                  + (abs_in_box_diff - (0.5 / sigma_2)) * (1. - smoothL1_sign)
    out_loss_box = bbox_outside_weights * in_loss_box
    loss_box = out_loss_box

    s = loss_box.size(0)
    loss_box = loss_box.view(s, -1).sum(1).mean()
    # for i in sorted(dim, reverse=True):
    #   loss_box = loss_box.sum(i)
    # loss_box = loss_box.mean()
    return loss_box

def _crop_pool_layer(bottom, rois, max_pool=True):
    # code modified from
    # https://github.com/ruotianluo/pytorch-faster-rcnn
    # implement it using stn
    # box to affine
    # input (x1,y1,x2,y2)
    """
    [  x2-x1             x1 + x2 - W + 1  ]
    [  -----      0      ---------------  ]
    [  W - 1                  W - 1       ]
    [                                     ]
    [           y2-y1    y1 + y2 - H + 1  ]
    [    0      -----    ---------------  ]
    [           H - 1         H - 1      ]
    """
    rois = rois.detach()
    batch_size = bottom.size(0)
    D = bottom.size(1)
    H = bottom.size(2)
    W = bottom.size(3)
    roi_per_batch = rois.size(0) / batch_size
    x1 = rois[:, 1::4] / 16.0
    y1 = rois[:, 2::4] / 16.0
    x2 = rois[:, 3::4] / 16.0
    y2 = rois[:, 4::4] / 16.0

    height = bottom.size(2)
    width = bottom.size(3)

    # affine theta
    zero = Variable(rois.data.new(rois.size(0), 1).zero_())
    theta = torch.cat([\
      (x2 - x1) / (width - 1),
      zero,
      (x1 + x2 - width + 1) / (width - 1),
      zero,
      (y2 - y1) / (height - 1),
      (y1 + y2 - height + 1) / (height - 1)], 1).view(-1, 2, 3)

    if max_pool:
      pre_pool_size = cfg.POOLING_SIZE * 2
      grid = F.affine_grid(theta, torch.Size((rois.size(0), 1, pre_pool_size, pre_pool_size)))
      bottom = bottom.view(1, batch_size, D, H, W).contiguous().expand(roi_per_batch, batch_size, D, H, W)\
                                                                .contiguous().view(-1, D, H, W)
      crops = F.grid_sample(bottom, grid)
      crops = F.max_pool2d(crops, 2, 2)
    else:
      grid = F.affine_grid(theta, torch.Size((rois.size(0), 1, cfg.POOLING_SIZE, cfg.POOLING_SIZE)))
      bottom = bottom.view(1, batch_size, D, H, W).contiguous().expand(roi_per_batch, batch_size, D, H, W)\
                                                                .contiguous().view(-1, D, H, W)
      crops = F.grid_sample(bottom, grid)

    return crops, grid

def _affine_grid_gen(rois, input_size, grid_size):

    rois = rois.detach()
    x1 = rois[:, 1::4] / 16.0
    y1 = rois[:, 2::4] / 16.0
    x2 = rois[:, 3::4] / 16.0
    y2 = rois[:, 4::4] / 16.0

    height = input_size[0]
    width = input_size[1]

    zero = Variable(rois.data.new(rois.size(0), 1).zero_())
    theta = torch.cat([\
      (x2 - x1) / (width - 1),
      zero,
      (x1 + x2 - width + 1) / (width - 1),
      zero,
      (y2 - y1) / (height - 1),
      (y1 + y2 - height + 1) / (height - 1)], 1).view(-1, 2, 3)

    grid = F.affine_grid(theta, torch.Size((rois.size(0), 1, grid_size, grid_size)))

    return grid

def _affine_theta(rois, input_size):

    rois = rois.detach()
    x1 = rois[:, 1::4] / 16.0
    y1 = rois[:, 2::4] / 16.0
    x2 = rois[:, 3::4] / 16.0
    y2 = rois[:, 4::4] / 16.0

    height = input_size[0]
    width = input_size[1]

    zero = Variable(rois.data.new(rois.size(0), 1).zero_())

    theta = torch.cat([\
      (y2 - y1) / (height - 1),
      zero,
      (y1 + y2 - height + 1) / (height - 1),
      zero,
      (x2 - x1) / (width - 1),
      (x1 + x2 - width + 1) / (width - 1)], 1).view(-1, 2, 3)

    return theta

def compare_grid_sample():
    # do gradcheck
    N = random.randint(1, 8)
    C = 2 # random.randint(1, 8)
    H = 5 # random.randint(1, 8)
    W = 4 # random.randint(1, 8)
    input = Variable(torch.randn(N, C, H, W).cuda(), requires_grad=True)
    input_p = input.clone().data.contiguous()

    grid = Variable(torch.randn(N, H, W, 2).cuda(), requires_grad=True)
    grid_clone = grid.clone().contiguous()

    out_offcial = F.grid_sample(input, grid)
    grad_outputs = Variable(torch.rand(out_offcial.size()).cuda())
    grad_outputs_clone = grad_outputs.clone().contiguous()
    grad_inputs = torch.autograd.grad(out_offcial, (input, grid), grad_outputs.contiguous())
    grad_input_off = grad_inputs[0]


    crf = RoICropFunction()
    grid_yx = torch.stack([grid_clone.data[:,:,:,1], grid_clone.data[:,:,:,0]], 3).contiguous().cuda()
    out_stn = crf.forward(input_p, grid_yx)
    grad_inputs = crf.backward(grad_outputs_clone.data)
    grad_input_stn = grad_inputs[0]
    pdb.set_trace()

    delta = (grad_input_off.data - grad_input_stn).sum()



##  add by lq
class FocalLoss(nn.Module):
    r"""
        This criterion is a implemenation of Focal Loss, which is proposed in
        Focal Loss for Dense Object Detection.

            Loss(x, class) = - \alpha (1-softmax(x)[class])^gamma \log(softmax(x)[class])

        The losses are averaged across observations for each minibatch.
        Args:
            alpha(1D Tensor, Variable) : the scalar factor for this criterion
            gamma(float, double) : gamma > 0; reduces the relative loss for well-classiﬁed examples (p > .5),
                                   putting more focus on hard, misclassiﬁed examples
            size_average(bool): size_average(bool): By default, the losses are averaged over observations for each minibatch.
                                However, if the field size_average is set to False, the losses are
                                instead summed for each minibatch.
    """

    def __init__(self, class_num, alpha=0.25, gamma=2, size_average=True):
        super(FocalLoss, self).__init__()
        if alpha is None:
            self.alpha = Variable(torch.ones(class_num, 1))
        else:
            if isinstance(alpha, Variable):
                self.alpha = alpha
            else:
                alpha = np.array([alpha,alpha],dtype= float).reshape(class_num,1)
                alpha = torch.DoubleTensor(alpha)
                self.alpha = Variable(alpha)
        self.gamma = gamma
        self.class_num = class_num
        self.size_average = size_average

    def forward(self, inputs, targets):
        N = inputs.size(0)
        C = inputs.size(1)
        P = F.softmax(inputs, dim=1)

        class_mask = inputs.data.new(N, C).fill_(0)
        class_mask = Variable(class_mask)
        ids = targets.view(-1, 1)
        class_mask.scatter_(1, ids.data, 1.)
        # print(class_mask)


        if inputs.is_cuda and not self.alpha.is_cuda:
            self.alpha = self.alpha.cuda()
        alpha = self.alpha[ids.data.view(-1)]
        probs = (P * class_mask).sum(1).view(-1, 1).type(torch.DoubleTensor).cuda()
        log_p = probs.log().type(torch.DoubleTensor).cuda()

        batch_loss = -alpha * (torch.pow((1 - probs), self.gamma)) * log_p

        if self.size_average:
            loss = batch_loss.mean()
        else:
            loss = batch_loss.sum()
        return loss


