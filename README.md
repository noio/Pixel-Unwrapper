>   __WARNING: EARLY ALPHA VERSION.__  
    __CAN CRASH BLENDER.__  
    __USE AT YOUR OWN RISK AND SAVE REGULARLY__  

    
# PixPaint add-on for Blender

[Overview Image: good pixel mapping vs bad]

This is an add-on for Blender that helps creating **Pixel Art 3D** or **lo-fi 3D**. This style looks best when:

1. Pixels align with edges on models
2. Pixels are roughly the same size across the model

Blender's standard unwrapping tools can make this tedious. I wrote this add-on to make that easier.


[![Walkthrough on YouTube](https://user-images.githubusercontent.com/271730/224333278-0fdfa82c-cd5d-4601-a2b8-563e29f4f493.png)](https://youtu.be/9ao1PM7GTS8)



# Installation

Go to [Releases](https://github.com/noio/pixpaint/releases/latest) and download the **Source code (zip)**. Then go to Blender Preferences, `Add-ons`, click `Install...` and select the .zip file.

# Features



## Pixels Per Unit

To make it easy to stick to a consistent pixel size across the model, you set your desired **Pixel Density** here. The [Unwrapping](#unwrapping) operators, as well as the [Rescale Selection](#rescale-selection) operator, use this to determine the UV scale.

Because most operators take into account Pixel Density and texture size, they will only work **if the active object has a texture**.

## Create Texture

If your model does not have a material with a texture yet, use this button to create them. It will also set the *Texture Interpolation* to *Closest*.

## Unwrapping

![Unwrapping](docs/unwrapping.png)

### Unwrap Basic

![Unwrap Basic](docs/unwrap_basic.png)

Performs a standard Blender Unwrap operation, but scales the result to match the Pixel Density. Then, it will scale and move the selection so that **the bounds align with pixel edges on the texture**. Internal vertices are not snapped to pixels

### Unwrap Grid

![Unwrap Grid](docs/unwrap_grid.png)

This is the tool I use most. It detects a **grid of quads** in the selection, and maps each **row and column** of that grid to the closest multiple of whole pixels (applying the Pixel Density). Any attached non-quads are unwrapped using Blender's standard unwrap. If the quads in your model are very deformed, so will the pixels. Before I wrote this plugin, I used the **Snap to Axis** operator from [UVSquares](https://www.blendermarket.com/products/uv-squares) and then scaled things manually to match the Pixel Density.

### Unwrap Extend

[Example Image]

### Unwrap to Single Pixel

![Unwrap to Single Pixel](docs/unwrap_to_single_pixel.png)

Sometimes you have a bunch of faces that you just want to fill with a color. This operator maps those to a single pixel on the texture. Each time you apply the operator, the selection is mapped to a free bit of texture so you can fill it with a different color.

## UV Editing

Explain Modes: **Destructive** vs **Preserve Texturing**

### Flip & Rotate

### Rescale Selection

[Example Image]

### Selection to Free Space

[Example Image]

The plugin assumes that **texture size is not an issue**. Pixel art textures are so small that efficient texture space usage is not a priority. By letting the plugin loosely pack UV islands onto the texture, the workflow is made a lot more flexible. It allows you to start texture painting before finalizing the UV mapping of a model, as there's always some extra space to paint newly added geometry later. If you're creating assets for a game and are worried about GPU memory, it's best to use a packing tool as a final step in the art pipeline. I recommend [SpriteUV](https://www.spriteuv.com).


### Selection to Random

[Example Image]

### Repack All

[Example Image]


## Caveats

- Texture used on multiple objects
- Objects with multiple textures