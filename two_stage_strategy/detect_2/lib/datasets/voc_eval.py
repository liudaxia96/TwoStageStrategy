# --------------------------------------------------------
# Fast/er R-CNN
# Licensed under The MIT License [see LICENSE for details]
# Written by Bharath Hariharan
# --------------------------------------------------------
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import xml.etree.ElementTree as ET
import os
import pickle
import numpy as np
import glob

def parse_rec(file_name):
	""" Parse a PASCAL VOC xml file """
	fits_file_name = file_name
	list_file_name = fits_file_name.split(".")[0] + '.list'
	array_from_txt = np.loadtxt(list_file_name)

	# 无目标的处理：
	if -1 in array_from_txt:
		print('There is no target in {}'.format(list_file_name.split("/")[-1]))
		return []

	objects = []
	objs_all_list = []
	if array_from_txt.size > 4:
		for step, value_single_row in enumerate(array_from_txt):
			if 0 < array_from_txt[step, 1] < cfg.TRAIN.TRIM_HEIGHT and 0 < array_from_txt[step, 2] < cfg.TRAIN.TRIM_HEIGHT:  ##  remove nagative coordinate(存在无目标的图像-1，-1)
				objs_all_list.append(value_single_row)
	else:
		if 0 < array_from_txt[1] < cfg.TRAIN.TRIM_HEIGHT and 0 < array_from_txt[2] < cfg.TRAIN.TRIM_HEIGHT:  ##  remove nagative coordinate(存在无目标的图像-1，-1)
			objs_all_list.append(array_from_txt)
	objs_all = np.array(objs_all_list)
	num_objs = objs_all.shape[0]
	padding = 4
	for obj in range(num_objs):
		obj_struct = {}
		x1 = int(objs_all[obj][1] - padding)
		x2 = int(objs_all[obj][1] + padding)
		y1 = int(objs_all[obj][2] - padding)
		y2 = int(objs_all[obj][2] + padding)
		obj_struct['bbox'] = [x1,y1,x2,y2]   ##  [xmin,ymin,xmax,ymax]
		obj_struct['name'] = 'EP'
		obj_struct['difficult'] = 0
		objects.append(obj_struct)

	return objects


def voc_ap(rec, prec, use_07_metric=False):
	""" ap = voc_ap(rec, prec, [use_07_metric])
	Compute VOC AP given precision and recall.
	If use_07_metric is true, uses the
	VOC 07 11 point method (default:False).
	"""
	if use_07_metric:
		# 11 point metric
		ap = 0.
		for t in np.arange(0., 1.1, 0.1):
			if np.sum(rec >= t) == 0:
				p = 0
			else:
				p = np.max(prec[rec >= t])
			ap = ap + p / 11.
	else:
		# correct AP calculation
		# first append sentinel values at the end
		mrec = np.concatenate(([0.], rec, [1.]))
		mpre = np.concatenate(([0.], prec, [0.]))

		# compute the precision envelope
		for i in range(mpre.size - 1, 0, -1):
			mpre[i - 1] = np.maximum(mpre[i - 1], mpre[i])

		# to calculate area under PR curve, look for points
		# where X axis (recall) changes value
		i = np.where(mrec[1:] != mrec[:-1])[0]

		# and sum (\Delta recall) * prec
		ap = np.sum((mrec[i + 1] - mrec[i]) * mpre[i + 1])
	return ap


def voc_eval(detpath,
             imagesetfile,
             classname,
             cachedir,
             ovthresh=0.5,
             use_07_metric=False):
	"""rec, prec, ap = voc_eval(detpath,
								annopath,
								imagesetfile,
								classname,
								[ovthresh],
								[use_07_metric])

	Top level function that does the PASCAL VOC evaluation.

	detpath: Path to detections
		detpath.format(classname) should produce the detection results file.
	annopath: Path to annotations
		annopath.format(imagename) should be the xml annotations file.
	imagesetfile: Text file containing the list of images, one image per line.
	classname: Category name (duh)
	cachedir: Directory for caching the annotations
	[ovthresh]: Overlap threshold (default = 0.5)
	[use_07_metric]: Whether to use VOC07's 11 point AP computation
		(default False)
	"""
	# assumes detections are in detpath.format(classname)
	# assumes annotations are in annopath.format(imagename)
	# assumes imagesetfile is a text file with each line an image name
	# cachedir caches the annotations in a pickle file

	# first load gt
	if not os.path.exists(cachedir):
		os.mkdir(cachedir)
	cachefile = os.path.join(cachedir, '%s_annots.pkl' % imagesetfile.split("data300-300-2")[0].split("/")[-1])
	# read list of images
	imagenames = glob.glob(imagesetfile)   ##  list file

	imagenames.sort()

	if not os.path.exists(cachefile):   # 判断文件是否存在！
		# load annotations
		recs = {}
		for i, imagename in enumerate(imagenames):
			recs[imagename] = parse_rec(imagename)
			if i % 10 == 0:
				print('Reading annotation for {:d}/{:d}'.format(
					i + 1, len(imagenames)))
		# save
		print('Saving cached annotations to {:s}'.format(cachefile))
		with open(cachefile, 'wb') as f:
			pickle.dump(recs, f)
	else:
		# load
		try:
			with open(cachefile, 'rb+') as f:
				try:
					recs = pickle.load(f)
				except:
					recs = pickle.load(f, encoding='bytes')
		except EOFError:
			return None

	# extract gt objects for this class
	class_recs = {}
	npos = 0
	for imagename in imagenames:
		if recs[imagename]:
			R = [obj for obj in recs[imagename] if obj['name'] == classname]
			bbox = np.array([x['bbox'] for x in R])
			difficult = np.array([x['difficult'] for x in R]).astype(np.bool)
			det = [False] * len(R)
			npos = npos + sum(~difficult)
			class_recs[imagename] = {'bbox': bbox,
									 'difficult': difficult,
									 'det': det}

	# read dets
	detfile = detpath.format(classname)
	with open(detfile, 'r') as f:
		lines = f.readlines()

	splitlines = [x.strip().split(' ') for x in lines]
	image_ids = [x[0] for x in splitlines]
	confidence = np.array([float(x[1]) for x in splitlines])
	BB = np.array([[float(z) for z in x[2:]] for x in splitlines])

	nd = len(image_ids)
	tp = np.zeros(nd)
	fp = np.zeros(nd)

	if BB.shape[0] > 0:
		# sort by confidence
		sorted_ind = np.argsort(-confidence)
		sorted_scores = np.sort(-confidence)
		BB = BB[sorted_ind, :]
		image_ids = [image_ids[x] for x in sorted_ind]

		# go down dets and mark TPs and FPs
		for d in range(nd):
			R = class_recs[image_ids[d]]
			bb = BB[d, :].astype(float)
			ovmax = -np.inf
			BBGT = R['bbox'].astype(float)

			if BBGT.size > 0:
				# compute overlaps
				# intersection
				ixmin = np.maximum(BBGT[:, 0], bb[0])
				iymin = np.maximum(BBGT[:, 1], bb[1])
				ixmax = np.minimum(BBGT[:, 2], bb[2])
				iymax = np.minimum(BBGT[:, 3], bb[3])
				iw = np.maximum(ixmax - ixmin + 1., 0.)
				ih = np.maximum(iymax - iymin + 1., 0.)
				inters = iw * ih

				# union
				uni = ((bb[2] - bb[0] + 1.) * (bb[3] - bb[1] + 1.) +
				       (BBGT[:, 2] - BBGT[:, 0] + 1.) *
				       (BBGT[:, 3] - BBGT[:, 1] + 1.) - inters)

				overlaps = inters / uni
				ovmax = np.max(overlaps)
				jmax = np.argmax(overlaps)

			if ovmax > ovthresh:
				if not R['difficult'][jmax]:
					if not R['det'][jmax]:
						tp[d] = 1.
						R['det'][jmax] = 1
					else:
						fp[d] = 1.
			else:
				fp[d] = 1.

	# compute precision recall
	fp = np.cumsum(fp)
	tp = np.cumsum(tp)
	rec = tp / float(npos)
	# avoid divide by zero in case the first detection matches a difficult
	# ground truth
	prec = tp / np.maximum(tp + fp, np.finfo(np.float64).eps)
	ap = voc_ap(rec, prec, use_07_metric)

	return rec, prec, ap
