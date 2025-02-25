import torch.optim
from torch.nn import BCELoss
import wandb
from torchvision import transforms
from modules.focus.mutual_gaze.focus_detection.utils.my_dataloader import MARIAData
from modules.focus.mutual_gaze.focus_detection.utils.model import JustOpenPose as Model
from tqdm import tqdm
from sklearn import metrics
import platform
import numpy as np
from utils.params import MutualGazeConfig

if __name__ == "__main__":

    is_local = "Windows" in platform.platform()

    config = MutualGazeConfig()
    dataset = "D:/datasets/mutualGaze_dataset" if is_local else "../mutualGaze_dataset"

    all_losses = []
    all_accuracies = []
    all_precisions = []
    all_recalls = []
    all_f1s = []

    for sess in range(5):
        train_data = MARIAData(dataset, mode="train", split_number=sess)
        train_loader = torch.utils.data.DataLoader(train_data, batch_size=config.batch_size,
                                                   num_workers=2 if is_local else 12, shuffle=True)
        valid_data = MARIAData(dataset, mode="valid", split_number=sess)
        valid_loader = torch.utils.data.DataLoader(valid_data, batch_size=32,
                                                   num_workers=2 if is_local else 4)
        test_data = MARIAData(dataset, mode="test", split_number=sess)
        test_loader = torch.utils.data.DataLoader(test_data, batch_size=32,
                                                  num_workers=2 if is_local else 2)

        model = Model()
        model.cuda()
        model.train()
        # for params in model.backbone.parameters():  # Freeze weights
        #     params.requires_grad = False

        loss_fn = BCELoss()
        optimizer = torch.optim.SGD(model.parameters(), lr=config.lr, momentum=0.9, weight_decay=1e-5)

        run = wandb.init(project="mutual_gaze", reinit=True, name="{}".format(sess),
                         settings=wandb.Settings(start_method='thread'), config=config.__dict__)
        wandb.watch(model, log='all', log_freq=config.log_every)

        print("Train set length: {}, valid set length: {}".format(len(train_loader) * config.batch_size,
                                                                  len(valid_loader) * config.batch_size))
        print("Train set watching: {}, not watching: {}".format(train_data.n_watch, train_data.n_not_watch))
        print("Valid set watching: {}, not watching: {}".format(valid_data.n_watch, valid_data.n_not_watch))
        print(train_data.sessions)
        print(valid_data.sessions)
        print(test_data.sessions)

        # for k in range(2):  # Try to unfreeze layers:
        #
        #     if k == 1:
        #         # model.load_state_dict(best_model)
        #         for parameter in list(model.backbone.parameters())[-2:]:
        #             parameter.requires_grad = True
        #         optimizer.param_groups[0]['params'] += list(model.backbone.parameters())[-2:]

        best_f1 = 0
        last_valid_loss = 10000
        best_valid_loss = 10000
        patience = config.patience

        best_model = None

        # Unfreeze a layer after 200 epoch
        after = 100
        how_many = 10
        layers = 0
        for epoch in range(config.n_epochs):
            # if epoch % after == 0 and epoch > 0:
            #     for k in range(how_many):
            #         list(model.backbone.parameters())[(-int(epoch/after)*how_many)-k].requires_grad = True
            #         layers += 1

            # TRAIN
            train_losses = []
            train_accuracies = []
            train_precisions = []
            train_recalls = []
            train_f1s = []
            outs = []
            model.train()
            for img, pose, img_, x, y in tqdm(train_loader, desc="Train epoch {}".format(epoch)):
                x = x.cuda().float()
                y = y.cuda().float()

                out = model(x)
                outs.append(out.detach().cpu().numpy())
                loss = loss_fn(out, y.float().unsqueeze(-1))
                loss.backward()
                optimizer.step()

                train_losses.append(loss.item())
                train_accuracies.append(metrics.accuracy_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5))
                train_precisions.append(metrics.precision_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5,
                                                                zero_division=0))
                train_recalls.append(metrics.recall_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5,
                                                          zero_division=0))
                train_f1s.append(metrics.f1_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5,
                                                  zero_division=0))

            # EVAL
            with torch.no_grad():
                valid_losses = []
                valid_accuracies = []
                valid_precisions = []
                valid_recalls = []
                valid_f1s = []
                model.eval()
                for img, pose, img_, x, y in tqdm(valid_loader, desc="Valid epoch {}".format(epoch)):
                    x = x.cuda().float()
                    y = y.cuda().float()

                    out = model(x)
                    outs.append(out.detach().cpu().numpy())
                    loss = loss_fn(out, y.float().unsqueeze(-1))

                    valid_losses.append(loss.item())
                    valid_accuracies.append(metrics.accuracy_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5))
                    valid_precisions.append(metrics.precision_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5,
                                                                    zero_division=0))
                    valid_recalls.append(metrics.recall_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5,
                                                              zero_division=0))
                    valid_f1s.append(metrics.f1_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5,
                                                      zero_division=0))

            wandb.log({"train/loss": sum(train_losses) / len(train_losses),
                       "train/accuracy": sum(train_accuracies) / len(train_accuracies),
                       "train/precision": sum(train_precisions) / len(train_precisions),
                       "train/recall": sum(train_recalls) / len(train_recalls),
                       "train/f1": sum(train_f1s) / len(train_f1s),
                       "valid/loss": sum(valid_losses) / len(valid_losses),
                       "valid/accuracy": sum(valid_accuracies) / len(valid_accuracies),
                       "valid/precision": sum(valid_precisions) / len(valid_precisions),
                       "valid/recall": sum(valid_recalls) / len(valid_recalls),
                       "valid/f1": sum(valid_f1s) / len(valid_f1s),
                       "lr": optimizer.param_groups[0]['lr'],
                       "predicted": wandb.Histogram(np.concatenate(outs, axis=0)),
                       "layers": layers})

            # Check if this is the best model
            score = sum(valid_f1s) / len(valid_f1s)
            if score > best_f1:
                best_f1 = score
                best_model = model.state_dict()
                torch.save(best_model, "sess_{}_f1_{:.2f}.pth".format(sess, best_f1))

            # Check patience
            # valid_loss = sum(valid_losses) / len(valid_losses)
            # if valid_loss > best_valid_loss:
            #     patience -= 1
            #     if patience == 0:
            #         break  # Exit the training loop
            # else:
            #     best_valid_loss = valid_loss
            #     patience = config.patience

        # TEST
        torch.save(best_model, "sess_{}_f1_{:.2f}.pth".format(sess, sum(valid_f1s) / len(valid_f1s)))
        test_losses = []
        test_accuracies = []
        test_precisions = []
        test_recalls = []
        test_f1s = []
        model.load_state_dict(best_model)
        model.eval()
        for (x, _), y in tqdm(test_loader, desc="Test session {}".format(sess)):
            x = x.permute(0, 3, 1, 2)
            x = x.cuda().float()
            y = y.cuda()

            out = model(x)
            loss = loss_fn(out, y.float().unsqueeze(-1))
            loss.backward()
            optimizer.step()

            test_losses.append(loss.item())
            test_accuracies.append(metrics.accuracy_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5))
            test_precisions.append(metrics.precision_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5,
                                                           zero_division=0))
            test_recalls.append(metrics.recall_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5,
                                                     zero_division=0))
            test_f1s.append(metrics.f1_score(y.detach().cpu() > 0.5, out.detach().cpu() > 0.5,
                                             zero_division=0))

        results = {"test/loss": sum(test_losses) / len(test_losses),
                   "test/accuracy": sum(test_accuracies) / len(test_accuracies),
                   "test/precision": sum(test_precisions) / len(test_precisions),
                   "test/recall": sum(test_recalls) / len(test_recalls),
                   "test/f1": sum(test_f1s) / len(test_f1s)}
        wandb.log(results)

        all_losses.append(sum(test_losses) / len(test_losses))
        all_accuracies.append(sum(test_accuracies) / len(test_accuracies))
        all_precisions.append(sum(test_precisions) / len(test_precisions))
        all_recalls.append(sum(test_recalls) / len(test_recalls))
        all_f1s.append(sum(test_f1s) / len(test_f1s))

        # with open("results.txt", "a") as outfile:
        #     outfile.write(str(results))

        run.finish()

    print("OVERALL LOSS: {}+-{}".format((sum(all_losses) / len(all_losses)), np.var(all_losses)))
    print("OVERALL ACCURACY: {}+-{}".format((sum(all_accuracies) / len(all_accuracies)), np.var(all_accuracies)))
    print("OVERALL PRECISION: {}+-{}".format((sum(all_precisions) / len(all_precisions)), np.var(all_precisions)))
    print("OVERALL RECALL: {}+-{}".format((sum(all_recalls) / len(all_recalls)), np.var(all_recalls)))
    print("OVERALL F1: {}+-{}".format((sum(all_f1s) / len(all_f1s)), np.var(all_f1s)))
