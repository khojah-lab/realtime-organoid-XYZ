# AI Use and Human Contribution

Ricki:
In data preprocessing, I used OpenAI Codex to help set up the preprocessing notebook, suggest methods and references, and improve the report’s grammar and wording. I read the suggested sources to understand the parameters, then tested different settings and compared the images myself. I selected the 2024 method based on clearer organoid boundaries and more consistent background brightness. I also reviewed the 2023 trial and decided not to apply it to the full set. 
Prompts: 
1. These organoid images have uneven illumination. What preprocessing methods could I compare, and what are their tradeoffs?
2. What criteria should I use to judge whether illumination correction is good? Please suggest relevant papers or documentation.
3. Based on the methods I decide to choose, set up the notebook

<<<<<<< Updated upstream
=======
Amy: 
I used OpenAI ChatGPT to assist with debugging code, implementing image processing methods, and improving notebook formatting. I also used AI to research and clarify technical concepts related to image analysis and preprocessing. I tested the suggested code and evaluated its outputs myself.
Prompts:
1. why am I getting this error
2. so like was the augmentatino originally not restricted to the training data
3. so is watershed segmentation able to tell distance from froeground to background?
4. examples of contrast normalization techniques
5. how does flat field address it directly though
6. can you fix the formatting is sucks
=======
>>>>>>> Stashed changes
---
### fitz_eda.ipynb

In data organization and exploratory analysis, I used Claude Code (Claude Sonnet 5.5) to extract the images from our source and write the EDA notebook. It parsed the image filenames into a metadata dataframe (filepath, source pptx, group, day). It also computed image properties, built the visualizations, and wrote the short descriptions next to each output. It inferred missingness from structure: skipped slide numbers, slides with fewer than the usual 6 images, gaps in day coverage, and the sparse KOLF condition × timepoint grid. It also checked for duplicates that remained after the original de-duplication. I reviewed the notebook's outputs and figures myself, and I chose the definition of "group" (slide number/condition depending on the batch). Results from Claude Code was tested by reviewing the Jupyter Notebook and making sure code functioned and made sense in the context of the project.

Prompts:
1. Read the two pptx files in this directory. Extract and save the images from both files, naming each as <pptx-name>-<category>-<day>. Save only unique images: skip duplicates and images without a day label. Save them in a separate folder for each deck.
2. Can you create an ipynb where you organize the data and run EDA on the images in @pptx_images/? For organizing the data, create a dataframe with the filepath and where each image came from (a column for the pptx it came from, the group if it has one, and the day taken). Short, brief descriptions of the visualizations or code output would be nice. Also, address missingness: duplicate and unlabeled images were removed from the original dataset.
<<<<<<< Updated upstream
=======
>>>>>>> 08c5dd1cac9e39fd0509db60373cf5532d469f02
>>>>>>> Stashed changes
