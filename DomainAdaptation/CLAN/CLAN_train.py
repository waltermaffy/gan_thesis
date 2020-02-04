import argparse
import torch
import torch.nn as nn
from torch.utils import data, model_zoo
import numpy as np
from torch.autograd import Variable
import torch.optim as optim
import torch.backends.cudnn as cudnn
import torch.nn.functional as F
import os, random
import os.path as osp
import time, timeit, datetime
from model.CLAN_G import Res_Deeplab
from model.CLAN_D import FCDiscriminator

from utils.loss import CrossEntropy2d
from utils.loss import WeightedBCEWithLogitsLoss
from utils.log import log_message, init_log
from dataset.gta5_dataset import GTA5DataSet
from dataset.synthia_dataset import SYNTHIADataSet
from dataset.cityscapes_dataset import cityscapesDataSet

IMG_MEAN = np.array((104.00698793, 116.66876762, 122.67891434), dtype=np.float32)

MODEL = 'ResNet'
BATCH_SIZE = 1
ITER_SIZE = 1
NUM_WORKERS = 4

IGNORE_LABEL = 255

MOMENTUM = 0.9
NUM_CLASSES = 19

RESTORE_FROM = './model/DeepLab_resnet_pretrained.pth'
# RESTORE_FROM_D = './snapshots/GTA2Cityscapes_CVPR_Syn0820_Wg00005weight005_dampingx2/GTA5_36000_D.pth' #For retrain

#RESTORE_FROM = '/media/data/walteraul_data/snapshots/CLAN_2k_GTA/GTA5_20001.pth'
#RESTORE_FROM_D = '/media/data/walteraul_data/snapshots/CLAN_2k_GTA/GTA5_20001_D.pth'

###
START_FROM_ITER = 0 #Default 0
####

SAVE_NUM_IMAGES = 2
SAVE_PRED_EVERY = 4000

# Hyper Paramters
WEIGHT_DECAY = 0.0005
LEARNING_RATE = 2.5e-4
LEARNING_RATE_D = 1e-4
NUM_STEPS = 48000
NUM_STEPS_STOP = 48000  # Use damping instead of early stopping
PREHEAT_STEPS = int(NUM_STEPS_STOP / 20)
POWER = 0.9
RANDOM_SEED = 1234
Lambda_weight = 0.01
Lambda_adv = 0.001
Lambda_local = 40
Epsilon = 0.4

SOURCE = 'GTA5'
INPUT_SIZE_SOURCE = [1280, 720]
DATA_DIRECTORY = '/media/data/walteraul_data/datasets/gta5_deeplab'
DATA_LIST_PATH = './dataset/gta5_list/train.txt'

TARGET = 'cityscapes'
INPUT_SIZE_TARGET = [1024, 512]
DATA_DIRECTORY_TARGET = '/media/data/walteraul_data/datasets/cityscapes'
DATA_LIST_PATH_TARGET = './dataset/cityscapes_list/train.txt'

SET = 'train'

EXPERIMENT = 'CLAN_GTA_Adapted'

SNAPSHOT_DIR = '/media/data/walteraul_data/snapshots/'
#SNAPSHOT_DIR = 'snapshots/'

LOG_DIR = 'log'

def get_arguments():
    """Parse all the arguments provided from the CLI.

    Returns:
      A list of parsed arguments.
    """
    parser = argparse.ArgumentParser(description="DeepLab-ResNet Network")
    parser.add_argument("--model", type=str, default=MODEL, help="available options : ResNet")
    parser.add_argument("--source", type=str, default=SOURCE, help="available options : GTA5, SYNTHIA")
    parser.add_argument("--target", type=str, default=TARGET, help="available options : cityscapes")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Number of images sent to the network in one step.")
    parser.add_argument("--iter-size", type=int, default=ITER_SIZE, help="Accumulate gradients for ITER_SIZE iterations.")
    parser.add_argument("--num-workers", type=int, default=NUM_WORKERS, help="number of workers for multithread dataloading.")
    parser.add_argument("--data-dir", type=str, default=DATA_DIRECTORY, help="Path to the directory containing the source dataset.")
    parser.add_argument("--data-list", type=str, default=DATA_LIST_PATH, help="Path to the file listing the images in the source dataset.")
    parser.add_argument("--ignore-label", type=int, default=IGNORE_LABEL, help="The index of the label to ignore during the training.")
    parser.add_argument("--input-size-source", type=str, default=INPUT_SIZE_SOURCE, help="Comma-separated string with height and width of source images.")
    parser.add_argument("--data-dir-target", type=str, default=DATA_DIRECTORY_TARGET, help="Path to the directory containing the target dataset.")
    parser.add_argument("--data-list-target", type=str, default=DATA_LIST_PATH_TARGET, help="Path to the file listing the images in the target dataset.")
    parser.add_argument("--input-size-target", type=str, default=INPUT_SIZE_TARGET, help="Comma-separated string with height and width of target images.")
    parser.add_argument("--is-training", action="store_true", help="Whether to updates the running means and variances during the training.")
    parser.add_argument("--learning-rate", type=float, default=LEARNING_RATE, help="Base learning rate for training with polynomial decay.")
    parser.add_argument("--learning-rate-D", type=float, default=LEARNING_RATE_D, help="Base learning rate for discriminator.")
    parser.add_argument("--momentum", type=float, default=MOMENTUM, help="Momentum component of the optimiser.")
    parser.add_argument("--not-restore-last", action="store_true", help="Whether to not restore last (FC) layers.")
    parser.add_argument("--num-classes", type=int, default=NUM_CLASSES, help="Number of classes to predict (including background).")
    parser.add_argument("--num-steps", type=int, default=NUM_STEPS, help="Number of training steps.")
    parser.add_argument("--num-steps-stop", type=int, default=NUM_STEPS_STOP, help="Number of training steps for early stopping.")
    parser.add_argument("--power", type=float, default=POWER, help="Decay parameter to compute the learning rate.")
    parser.add_argument("--random-mirror", action="store_true", help="Whether to randomly mirror the inputs during the training.")
    parser.add_argument("--random-scale", action="store_true", help="Whether to randomly scale the inputs during the training.")
    parser.add_argument("--random-seed", type=int, default=RANDOM_SEED, help="Random seed to have reproducible results.")
    parser.add_argument("--log-dir", type=str, default=LOG_DIR, help="Where to save log of the model.")
    parser.add_argument("--restore-from", type=str, default=RESTORE_FROM, help="Where restore model parameters from.")
    parser.add_argument("--start-from-iter", type=str, default=START_FROM_ITER, help="Where start model parameters from.")
    parser.add_argument("--save-num-images", type=int, default=SAVE_NUM_IMAGES, help="How many images to save.")
    parser.add_argument("--save-pred-every", type=int, default=SAVE_PRED_EVERY, help="Save summaries and checkpoint every often.")
    parser.add_argument("--snapshot-dir", type=str, default=SNAPSHOT_DIR, help="Where to save snapshots of the model.")
    parser.add_argument("--experiment", type=str, default=EXPERIMENT, help="Experiment name")
    parser.add_argument("--weight-decay", type=float, default=WEIGHT_DECAY, help="Regularisation parameter for L2-loss.")
    parser.add_argument("--gpu", type=int, default=0, help="choose gpu device.")
    parser.add_argument("--cpu", action='store_true', help="choose to use cpu device.")
    parser.add_argument("--set", type=str, default=SET, help="choose adaptation set.")

    return parser.parse_args()


args = get_arguments()


def loss_calc(pred, label, device):
    """
    This function returns cross entropy loss for semantic segmentation
    """
    # out shape batch_size x channels x h x w -> batch_size x channels x h x w
    # label shape h x w x 1 x batch_size  -> batch_size x 1 x h x w
    label = label.long().to(device)
    criterion = CrossEntropy2d(NUM_CLASSES).to(device)
    return criterion(pred, label)


def lr_poly(base_lr, iter, max_iter, power):
    return base_lr * ((1 - float(iter) / max_iter) ** (power))


def lr_warmup(base_lr, iter, warmup_iter):
    return base_lr * (float(iter) / warmup_iter)


def adjust_learning_rate(optimizer, i_iter):
    if i_iter < PREHEAT_STEPS:
        lr = lr_warmup(args.learning_rate, i_iter, PREHEAT_STEPS)
    else:
        lr = lr_poly(args.learning_rate, i_iter, args.num_steps, args.power)
    optimizer.param_groups[0]['lr'] = lr
    if len(optimizer.param_groups) > 1:
        optimizer.param_groups[1]['lr'] = lr * 10


def adjust_learning_rate_D(optimizer, i_iter):
    if i_iter < PREHEAT_STEPS:
        lr = lr_warmup(args.learning_rate_D, i_iter, PREHEAT_STEPS)
    else:
        lr = lr_poly(args.learning_rate_D, i_iter, args.num_steps, args.power)
    optimizer.param_groups[0]['lr'] = lr
    if len(optimizer.param_groups) > 1:
        optimizer.param_groups[1]['lr'] = lr * 10


def weightmap(pred1, pred2):
    output = 1.0 - torch.sum((pred1 * pred2), 1).view(1, 1, pred1.size(2), pred1.size(3)) / \
             (torch.norm(pred1, 2, 1) * torch.norm(pred2, 2, 1)).view(1, 1, pred1.size(2), pred1.size(3))
    return output


def main():
    """Create the model and start the training."""

    cudnn.enabled = True
    cudnn.benchmark = True

    device = torch.device("cuda" if not args.cpu else "cpu")

    random.seed(args.random_seed)

    snapshot_dir = os.path.join(args.snapshot_dir, args.experiment)
    log_dir = os.path.join(args.log_dir, args.experiment)
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(snapshot_dir, exist_ok=True)

    log_file = os.path.join(log_dir, 'log.txt')

    init_log(log_file, args)

    # =============================================================================
    # INIT G
    # =============================================================================
    if MODEL == 'ResNet':
        model = Res_Deeplab(num_classes=args.num_classes, restore_from=args.restore_from)
    model.train()
    model.to(device)

    # =============================================================================
    # INIT D
    # =============================================================================

    model_D = FCDiscriminator(num_classes=args.num_classes)

   # saved_state_dict_D = torch.load(RESTORE_FROM_D) #for retrain
   # model_D.load_state_dict(saved_state_dict_D)

    model_D.train()
    model_D.to(device)

# DataLoaders
    trainloader = data.DataLoader(GTA5DataSet(args.data_dir, args.data_list, max_iters=args.num_steps * args.iter_size * args.batch_size,
                                            crop_size=args.input_size_source, scale=True, mirror=True, mean=IMG_MEAN),
                                            batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers, pin_memory=True)
    trainloader_iter = enumerate(trainloader)

    targetloader = data.DataLoader(cityscapesDataSet(args.data_dir_target, args.data_list_target,
                                                     max_iters=args.num_steps * args.iter_size * args.batch_size, crop_size=args.input_size_target, scale=True, mirror=True,
                                                     mean=IMG_MEAN, set=args.set), batch_size=args.batch_size, shuffle=True,num_workers=args.num_workers, pin_memory=True)
    targetloader_iter = enumerate(targetloader)

# Optimizers
    optimizer = optim.SGD(model.optim_parameters(args), lr=args.learning_rate, momentum=args.momentum, weight_decay=args.weight_decay)
    optimizer.zero_grad()
    optimizer_D = optim.Adam(model_D.parameters(), lr=args.learning_rate_D, betas=(0.9, 0.99))
    optimizer_D.zero_grad()

# Losses
    bce_loss = torch.nn.BCEWithLogitsLoss()
    weighted_bce_loss = WeightedBCEWithLogitsLoss()

    interp_source = nn.Upsample(size=(args.input_size_source[1], args.input_size_source[0]), mode='bilinear', align_corners=True)
    interp_target = nn.Upsample(size=(args.input_size_target[1], args.input_size_target[0]), mode='bilinear', align_corners=True)

# Labels for Adversarial Training
    source_label = 0
    target_label = 1

    # ======================================================================================
    # Start training
    # ======================================================================================
    print('###########   TRAINING STARTED  ############')
    start = time.time()

    for i_iter in range(args.start_from_iter, args.num_steps):

        optimizer.zero_grad()
        adjust_learning_rate(optimizer, i_iter)

        optimizer_D.zero_grad()
        adjust_learning_rate_D(optimizer_D, i_iter)

        damping = (1 - (i_iter) / NUM_STEPS)

        # ======================================================================================
        # train G
        # ======================================================================================

        # Remove Grads in D
        for param in model_D.parameters():
            param.requires_grad = False

        # Train with Source
        _, batch = next(trainloader_iter)
        images_s, labels_s, _, _ = batch
        images_s = images_s.to(device)
        pred_source1, pred_source2 = model(images_s)

        pred_source1 = interp_source(pred_source1)
        pred_source2 = interp_source(pred_source2)

        # Segmentation Loss
        loss_seg = (loss_calc(pred_source1, labels_s, device) + loss_calc(pred_source2, labels_s, device))
        loss_seg.backward()

        # Train with Target
        _, batch = next(targetloader_iter)
        images_t, _, _ = batch
        images_t = images_t.to(device)

        pred_target1, pred_target2 = model(images_t)

        pred_target1 = interp_target(pred_target1)
        pred_target2 = interp_target(pred_target2)

        weight_map = weightmap(F.softmax(pred_target1, dim=1), F.softmax(pred_target2, dim=1))

        D_out = interp_target(model_D(F.softmax(pred_target1 + pred_target2, dim=1)))

        # Adaptive Adversarial Loss
        if i_iter > PREHEAT_STEPS:
            loss_adv = weighted_bce_loss(D_out, torch.FloatTensor(D_out.data.size()).fill_(source_label).to(device), weight_map, Epsilon, Lambda_local)
        else:
            loss_adv = bce_loss(D_out, torch.FloatTensor(D_out.data.size()).fill_(source_label).to(device))

        loss_adv = loss_adv * Lambda_adv * damping
        loss_adv.backward()

        # Weight Discrepancy Loss
        W5 = None
        W6 = None
        if args.model == 'ResNet':

            for (w5, w6) in zip(model.layer5.parameters(), model.layer6.parameters()):
                if W5 is None and W6 is None:
                    W5 = w5.view(-1)
                    W6 = w6.view(-1)
                else:
                    W5 = torch.cat((W5, w5.view(-1)), 0)
                    W6 = torch.cat((W6, w6.view(-1)), 0)

        loss_weight = (torch.matmul(W5, W6) / (torch.norm(W5) * torch.norm(W6)) + 1)  # +1 is for a positive loss
        loss_weight = loss_weight * Lambda_weight * damping * 2
        loss_weight.backward()

        # ======================================================================================
        # train D
        # ======================================================================================

        # Bring back Grads in D
        for param in model_D.parameters():
            param.requires_grad = True

        # Train with Source
        pred_source1 = pred_source1.detach()
        pred_source2 = pred_source2.detach()

        D_out_s = interp_source(model_D(F.softmax(pred_source1 + pred_source2, dim=1)))

        loss_D_s = bce_loss(D_out_s, torch.FloatTensor(D_out_s.data.size()).fill_(source_label).to(device))

        loss_D_s.backward()

        # Train with Target
        pred_target1 = pred_target1.detach()
        pred_target2 = pred_target2.detach()
        weight_map = weight_map.detach()

        D_out_t = interp_target(model_D(F.softmax(pred_target1 + pred_target2, dim=1)))

        # Adaptive Adversarial Loss
        if (i_iter > PREHEAT_STEPS):
            loss_D_t = weighted_bce_loss(D_out_t, torch.FloatTensor(D_out_t.data.size()).fill_(target_label).to(device), weight_map, Epsilon, Lambda_local)
        else:
            loss_D_t = bce_loss(D_out_t,torch.FloatTensor(D_out_t.data.size()).fill_(target_label).to(device))

        loss_D_t.backward()

        optimizer.step()
        optimizer_D.step()

        if (i_iter) % 10 == 0:
            log_message('Iter = {0:6d}/{1:6d}, loss_seg = {2:.4f} loss_adv = {3:.4f}, loss_weight = {4:.4f}, loss_D_s = {5:.4f} loss_D_t = {6:.4f}'.format(
                i_iter, args.num_steps, loss_seg, loss_adv, loss_weight, loss_D_s, loss_D_t), log_file)

        if (i_iter % args.save_pred_every == 0 and i_iter != 0) or i_iter == args.num_steps-1:
            i_iter = i_iter if i_iter != self.num_steps - 1 else i_iter + 1  # for last iter
            print('saving weights...')
            torch.save(model.state_dict(), osp.join(snapshot_dir, 'GTA5_' + str(i_iter) + '.pth'))
            torch.save(model_D.state_dict(), osp.join(snapshot_dir, 'GTA5_' + str(i_iter) + '_D.pth'))

    end = time.time()
    log_message('Total training time: {} days, {} hours, {} min, {} sec '.format(
        int((end - start) / 86400), int((end - start)/3600), int((end - start)/60%60), int((end - start)%60)), log_file)
    print('### Experiment: ' + args.experiment + ' finished ###')

if __name__ == '__main__':
    os.system('nvidia-smi -q -d Memory |grep -A4 GPU|grep Free >tmp')
    memory_gpu = [int(x.split()[2]) for x in open('tmp', 'r').readlines()]
    os.system('rm tmp')
    gpu_target = str(np.argmax(memory_gpu))
    os.environ["CUDA_VISIBLE_DEVICES"] = gpu_target
    print('Training on GPU ' + gpu_target)
    main()
