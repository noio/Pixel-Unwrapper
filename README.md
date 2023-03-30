# PixPaint add-on for Blender

[Overview Image: good pixel mapping vs bad]

This is a plugin for Blender that makes it easier to create 3D models with a style called _"Pixel Art 3D"_ or _"lo-fi 3D."_ This style looks best when you follow a few guidelines:

1. Pixels should align with edges on models
2. Pixels should be roughly the same size across the model
3. Details on the model should be roughly the same size as pixels (or a multiple)
4. If possible, details should be on the texture (using transparency), rather than geometry.    

Blender's standard unwrapping tools can be inefficient for this workflow. This plugin aims to help with that.

>   __WARNING: EARLY ALPHA VERSION.__  
    __CAN CRASH BLENDER.__  
    __USE AT YOUR OWN RISK AND SAVE REGULARLY__  


# Installation

Go to [Releases](https://github.com/noio/pixpaint/releases/latest) and download the **Source code (zip)**. Then go to Blender Preferences, `Add-ons`, click `Install...` and select the .zip file.

# Features

[![Walkthrough on YouTube](https://user-images.githubusercontent.com/271730/224333278-0fdfa82c-cd5d-4601-a2b8-563e29f4f493.png)](https://youtu.be/9ao1PM7GTS8)

The plugin assumes that **texture size is not an issue**. When working with pixel art textures of 32, 64, or maybe 128 pixels in size, texture space efficiency is not a concern. By letting the plugin coarsely pack UV islands onto the texture, the workflow is made a lot more flexible. It allows you to go back and edit geometry after texturing, and have free space for texturing that geometry. If you're creating assets for a game and are worried about GPU memory, it's best to use a packing tool as a final step in the art pipeline. I recommend [SpriteUV](https://www.spriteuv.com).

## Pixels Per Unit

To make it easy to stick to a consistent pixel size across the model, you set your desired **Pixel Density** here. The [Unwrapping](#unwrapping) operators, as well as the [Rescale Selection](#rescale-selection) operator, use this to determine the UV scale.

Because most operators take into account Pixel Density and texture size, they will only work **if the active object has a texture**.

## Create Texture

If your model does not have a material with a texture yet, use this button to create those. This is just a shorthand to save a few seconds of clicking in Blender. What it does:

- Create a new *Texture*
- Create a new *Material* for the selected object
- Set the texture as the Material's *Base Color*
- Set the *Texture Interpolation* to *Closest*

## Unwrapping

### Unwrap Basic

[Example Image]



### Unwrap Grid

[Example Image]

### Unwrap Extend

[Example Image]

### Unwrap to Single Pixel

[Example Image]

## UV Editing

Explain Modes: **Destructive** vs **Preserve Texturing**

### Flip & Rotate

### Rescale Selection

[Example Image]

### Selection to Free Space

[Example Image]

### Selection to Random

[Example Image]

### Repack All

[Example Image]


## Caveats

- Texture used on multiple objects
- Objects with multiple textures