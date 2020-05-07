from .abstract import Processor, SequentialProcessor
from . import processors as pr


class AugmentImage(SequentialProcessor):
    def __init__(self):
        super(AugmentImage, self).__init__()
        self.add(pr.RandomContrast())
        self.add(pr.RandomBrightness())
        self.add(pr.RandomSaturation())
        self.add(pr.RandomHue())


class AugmentBoxes(SequentialProcessor):
    def __init__(self, mean=pr.BGR_IMAGENET_MEAN):
        super(AugmentBoxes, self).__init__()
        self.add(pr.ToAbsoluteBoxCoordinates())
        self.add(pr.Expand(mean=mean))
        self.add(pr.RandomSampleCrop())
        self.add(pr.RandomFlipBoxesLeftRight())
        self.add(pr.ToNormalizedBoxCoordinates())


class PreprocessImage(SequentialProcessor):
    def __init__(self, shape, mean=pr.BGR_IMAGENET_MEAN):
        super(PreprocessImage, self).__init__()
        self.add(pr.ResizeImage(shape))
        self.add(pr.CastImage(float))
        if mean is None:
            self.add(pr.NormalizeImage())
        else:
            self.add(pr.SubtractMeanImage(mean))


class PreprocessBoxes(SequentialProcessor):
    def __init__(self, num_classes, prior_boxes, IOU, variances):
        super(PreprocessBoxes, self).__init__()
        self.add(pr.MatchBoxes(prior_boxes, IOU),)
        self.add(pr.EncodeBoxes(prior_boxes, variances))
        self.add(pr.BoxClassToOneHotVector(num_classes))


class AugmentDetection(SequentialProcessor):
    def __init__(self, prior_boxes, split=pr.TRAIN, num_classes=21, size=300,
                 mean=pr.BGR_IMAGENET_MEAN, IOU=.5, variances=[.1, .2]):
        super(AugmentDetection, self).__init__()

        self.augment_image = AugmentImage()
        self.augment_image.insert(0, pr.LoadImage())
        self.augment_image.add(pr.ConvertColorSpace(pr.RGB2BGR))
        self.preprocess_image = PreprocessImage((size, size), mean)

        self.augment_boxes = AugmentBoxes()
        args = (num_classes, prior_boxes, IOU, variances)
        self.preprocess_boxes = PreprocessBoxes(*args)

        self.add(pr.UnpackDictionary(['image', 'boxes']))
        self.add(pr.ControlFlow(self.augment_image, [0], [0]))
        self.add(pr.ControlFlow(self.augment_boxes, [0, 1], [0, 1]))
        if split == pr.TRAIN:
            self.add(pr.ControlFlow(self.preprocess_image, [0], [0]))
            self.add(pr.ControlFlow(self.preprocess_boxes, [1], [1]))
        self.add(pr.OutputWrapper(
            {0: {'image': (size, size, 3)}},
            {1: {'boxes': (len(prior_boxes), 4 + num_classes)}}))


class SingleShotInference(Processor):
    def __init__(self, model, class_names, score_thresh, nms_thresh,
                 mean=pr.BGR_IMAGENET_MEAN):
        super(SingleShotInference, self).__init__()
        preprocessing = SequentialProcessor(
            [pr.ResizeImage(model.input_shape[1:3]),
             pr.ConvertColorSpace(pr.RGB2BGR),
             pr.SubtractMeanImage(mean),
             pr.CastImage(float),
             pr.ExpandDims(axis=0)])
        postprocessing = SequentialProcessor(
            [pr.Squeeze(axis=None),
             pr.DecodeBoxes(model.prior_boxes, variances=[.1, .2]),
             pr.NonMaximumSuppressionPerClass(nms_thresh),
             pr.FilterBoxes(class_names, score_thresh)])
        self.denormalize_boxes2D = pr.DenormalizeBoxes2D()
        self.predict = pr.Predict(model, preprocessing, postprocessing)
        self.draw_boxes2D = pr.DrawBoxes2D(class_names)

    def call(self, image):
        boxes2D = self.predict(image)
        boxes2D = self.denormalize_boxes2D(image, boxes2D)
        image = self.draw_boxes2D(image, boxes2D)
        return image
