""" Helpers without an obvious logical home. """

from collections import defaultdict, Iterable
import copy
import glob
import logging
import os

from peppy import \
    FLAGS, SAMPLE_INDEPENDENT_PROJECT_SECTIONS, SAMPLE_NAME_COLNAME
from .const import *


def get_logger(name):
    l = logging.getLogger(name)
    l.whisper = lambda msg, *args, **kwargs: l.log(5, msg, *args, **kwargs)
    return l


_LOGGER = get_logger(__name__)


def create_looper_args_text(pl_key, submission_settings, prj):
    """

    :param str pl_key: Strict/exact pipeline key, the hook into the project's
        pipeline configuration data
    :param dict submission_settings: Mapping from settings
        key to value, used to determine resource request
    :param Project prj: Project data, used for metadata and pipeline
        configuration information
    :return str: text representing the portion of a command generated by
        looper options and arguments
    """

    # Start with copied settings and empty arguments text
    submission_settings = copy.deepcopy(submission_settings)
    opt_arg_pairs = [("-O", prj.metadata[RESULTS_SUBDIR_KEY])]

    if hasattr(prj, "pipeline_config"):
        # Index with 'pl_key' instead of 'pipeline'
        # because we don't care about parameters here.
        if hasattr(prj.pipeline_config, pl_key):
            # First priority: pipeline config in project config
            pl_config_file = getattr(prj.pipeline_config, pl_key)
            # Make sure it's a file (it could be provided as null.)
            if pl_config_file:
                if not os.path.isfile(pl_config_file):
                    _LOGGER.error(
                        "Pipeline config file specified "
                        "but not found: %s", pl_config_file)
                    raise IOError(pl_config_file)
                _LOGGER.info("Found config file: %s", pl_config_file)
                # Append arg for config file if found
                opt_arg_pairs.append(("-C", pl_config_file))
        else:
            _LOGGER.debug("No pipeline configuration: %s", pl_key)
    else:
        _LOGGER.debug("Project lacks pipeline configuration")

    num_cores = int(submission_settings.setdefault("cores"))
    if num_cores > 1:
        opt_arg_pairs.append(("-P", num_cores))

    try:
        mem_alloc = submission_settings["mem"]
    except KeyError:
        _LOGGER.warning("Submission settings lack memory specification")
    else:
        if float(mem_alloc) > 1:
            opt_arg_pairs.append(("-M", mem_alloc))

    looper_argtext = " ".join(["{} {}".format(opt, arg)
                               for opt, arg in opt_arg_pairs])
    return looper_argtext


def fetch_flag_files(prj=None, results_folder="", flags=FLAGS):
    """
    Find all flag file paths for the given project.

    :param Project | AttributeDict prj: full Project or AttributeDict with
        similar metadata and access/usage pattern
    :param str results_folder: path to results folder, corresponding to the
        1:1 sample:folder notion that a looper Project has. That is, this
        function uses the assumption that if results_folder rather than project
        is provided, the structure of the file tree rooted at results_folder is
        such that any flag files to be found are not directly within rootdir but
        are directly within on of its first layer of subfolders.
    :param Iterable[str] | str flags: Collection of flag names or single flag
        name for which to fetch files
    :return Mapping[str, list[str]]: collection of filepaths associated with
        particular flag for samples within the given project
    :raise TypeError: if neither or both of project and rootdir are given
    """

    if not (prj or results_folder) or (prj and results_folder):
        raise TypeError("Need EITHER project OR rootdir")

    # Just create the filenames once, and pair once with flag name.
    flags = [flags] if isinstance(flags, str) else list(flags)
    flagfile_suffices = ["*{}.flag".format(f) for f in flags]
    flag_suffix_pairs = list(zip(flags, flagfile_suffices))

    # Collect the flag file paths by flag name.
    files_by_flag = defaultdict(list)

    if prj is None:
        for flag, suffix in flag_suffix_pairs:
            flag_expr = os.path.join(results_folder, "*", suffix)
            flags_present = glob.glob(flag_expr)
            files_by_flag[flag] = flags_present
    else:
        # Iterate over samples to collect flag files.
        for s in prj.samples:
            folder = sample_folder(prj, s)
            # Check each candidate flag for existence, collecting if present.
            for flag, suffix in flag_suffix_pairs:
                flag_expr = os.path.join(folder, suffix)
                flags_present = glob.glob(flag_expr)
                files_by_flag[flag].extend(flags_present)

    return files_by_flag


def fetch_sample_flags(prj, sample, pl_names=None):
    """
    Find any flag files present for a sample associated with a project

    :param looper.Project prj: project of interest
    :param peppy.Sample sample: sample of interest
    :param str | Iterable[str] pl_names: name of the pipeline for which flag(s)
        should be found
    :return Iterable[str]: collection of flag file path(s) associated with the
        given sample for the given project
    """
    sfolder = sample_folder(prj=prj, sample=sample)
    assert os.path.isdir(sfolder), "Missing sample folder: {}".format(sfolder)
    if not pl_names:
        pl_match = lambda _: True
    else:
        if isinstance(pl_names, str):
            pl_names = [pl_names]
        pl_match = lambda n: any(n.startswith(pl) for pl in pl_names)
    return [os.path.join(sfolder, f) for f in os.listdir(sfolder)
            if os.path.splitext(f)[1] == ".flag" and pl_match(f)]


def grab_project_data(prj):
    """
    From the given Project, grab Sample-independent data.

    There are some aspects of a Project of which it's beneficial for a Sample
    to be aware, particularly for post-hoc analysis. Since Sample objects
    within a Project are mutually independent, though, each doesn't need to
    know about any of the others. A Project manages its, Sample instances,
    so for each Sample knowledge of Project data is limited. This method
    facilitates adoption of that conceptual model.

    :param Project prj: Project from which to grab data
    :return Mapping: Sample-independent data sections from given Project
    """

    if not prj:
        return {}

    data = {}
    for section in SAMPLE_INDEPENDENT_PROJECT_SECTIONS:
        try:
            data[section] = prj[section]
        except KeyError:
            _LOGGER.debug("Project lacks section '%s', skipping", section)

    return data


def partition(items, test):
    """
    Partition items into a pair of disjoint multisets,
    based on the evaluation of each item as input to boolean test function.
    There are a couple of evaluation options here. One builds a mapping
    (assuming each item is hashable) from item to boolean test result, then
    uses that mapping to partition the elements on a second pass.
    The other simply is single-pass, evaluating the function on each item.
    A time-costly function suggests the two-pass, mapping-based approach while
    a large input suggests a single-pass approach to conserve memory. We'll
    assume that the argument is not terribly large and that the function is
    cheap to compute and use a simpler single-pass approach.

    :param Sized[object] items: items to partition
    :param function(object) -> bool test: test to apply to each item to
        perform the partitioning procedure
    :return: list[object], list[object]: partitioned items sequences
    """
    passes, fails = [], []
    _LOGGER.whisper("Testing {} items: {}".format(len(items), items))
    for item in items:
        _LOGGER.whisper("Testing item {}".format(item))
        group = passes if test(item) else fails
        group.append(item)
    return passes, fails


def sample_folder(prj, sample):
    """
    Get the path to this Project's root folder for the given Sample.

    :param AttributeDict | Project prj: project with which sample is associated
    :param Mapping sample: Sample or sample data for which to get root output
        folder path.
    :return str: this Project's root folder for the given Sample
    """
    return os.path.join(prj.metadata[RESULTS_SUBDIR_KEY],
                        sample[SAMPLE_NAME_COLNAME])
