"""
This class is an initial proof-of-concept implementation of PySyft's Differential Privacy
infrastructure. In particular, we want to provide the ability to automatically compute
the Sensitivity of a function. If you're unsure what Sensitivity or Differential Privacy
is, here are a couple of great resources:

- https://www.cis.upenn.edu/~aaroth/Papers/privacybook.pdf
- https://github.com/frankmcsherry/blog/blob/master/posts/2016-02-03.md

You can also find more information about Differential Privacy in the
#differential_privacy channel of OpenMined's slack.

This class keeps track of a per-user sensitivity and then returns the max sensitivity
across all users. Each user's sensitivity is intuitively a calculation of the maximum
amount (positively or negatively) that the output of a function would change if that
person were removed from the calculation. For example

If Bob had a variable:

    x = 5

and Alice had a variable

    y = 6

A function on these values might be

z = x + y

This tensor seeks to answer the question "what is the maximum amount z would change
if Bob or Alice were not included in the computation?". At first, one might say that
"the max for Bob is 5 and the max for Alice is 6." However, this is incorrect. In fact,
if we assume that Alice and Bob could have set their input variables to be *anything*
then the sensitivity is actually infinite.

Thus, by default, any value should have infinite sensitivity.

It is only by bounding the max/min possible value that we can track non-infinite sensitivity.
We can do this in a myriad of ways, but the easiest way is to simply use a threshold. Perhpas:

x =  max(min(5, 10), 0) # Bob's input

y =  max(min(6, 10), 0) # Alice's input

In this case, we would now know that Bob and Alice's numbers are both bounded to be between 0
and 10. Now we know that the following:

z = x + y

has a maximum sensitivity of 10 because the most the output could change by removing any user's
input is 10. Note that the max value z could actually take is 20, but this is different from
the max sensitivity.

The goal of this tensor is to make this kind of logic automatically happen on tensor objects so
that we can chan arbitrary tensor commands one after the other and always keep track of the
maximum amount that the output would change if ANY user were removed. This means we keep track
of the maximum positive and negative change any entity can have on any tensor value. In the case
that only one entity contributes to a variable (i.e., they initialized the variable), then the
min/max amount that entity contributes to their value also corresponds to the min/max value that
variable can take on.

We compute sensitivity because it's an important input to many important functions in Differential
Privacy.
"""


import torch as th

# TODO: determine max according to type(self.values)
max_long = 2 ** 62


class SensitivityTensor:
    def __init__(
        self,
        values: th.Tensor,
        max_ent_conts: th.Tensor,
        min_ent_conts: th.Tensor,
        entities: th.Tensor,
    ):
        """Initializes sensitivity tensor.

        Args:
            values (torch.Tensor): the actual data points - can be any dimension
            max_ent_conts (torch.Tensor): the maximum (or min negative) amount any entity contributes to any value.
                You can simply think of max_ent_conts as a recording of the maximum possible value
                this tensor could take on given the maximum possible value of all of the input values
                (from other tensors in this tensor's "ancestry") used to create it. However, this is only
                actually the case for the sum over the last dimension of the tensor.
                Theoretically we always interpret self.values as a sum over contributions from
                all possible known entities (which can be represented in a sparse matrix. TODO: test)
                Given this representation, self.max_ent_conts can be thought of as the maximum amount
                that any entity could have added into self.values. Note, that if only one entity
                is contributing to a datapoint, then the max val of that entry in the tensor is
                also the maximum that entry in the tensor can take. self.max_ent_conts should be the same
                shape as self.values with an extra dimension at the end which is as long as the
                number of known entities. TODO: add support for sparse recording of known entities


            min_ent_conts (torch.Tensor): The minimum (or max negative) amount any entity contributes to any value.
                Same as self.max_ent_conts but instead of recording the maximum amount any entity
                adds to create self.values, it records the maximum amount any entity could be
                subtracting to create self.values. Summing across the last dimension returns the
                minimum possible value that each entry in self.values could possibly be given the
                possible range within the tensors used to create it (it's "ancestry").

            entities (torch.Tensor): a matrix of 1s and 0s which corresponds to whether or not a given entity
                was used to help encode a specific value. TODO: remove this tensor & sparsely encode max_ent_conts/min_ent_conts
                TODO (cont): instead.
        """

        self.values = values

        # to be clear, every entry in self.values has a list of corresponding entries, one for each entity.
        # Thus, self.max_ent_conts and self.min_ent_conts are the same shape as self.values with on added dimension
        # at the end of length #num entities (number of known entities - which must be known a-prior ATM)

        self.max_ent_conts = max_ent_conts  # (self.values.shape..., #num entities)
        self.min_ent_conts = min_ent_conts  # (self.values.shape..., #num entities)

        # one hot encoding of entities in the ancestry of this tensor
        self.entities = entities  # (self.values.shape..., #num entities)

    def __add__(self, other):
        """Adds the self tensor with a tensor or a scalar/tensor of equal shape, keeping track of sensitivity
        appropriately.

        Args:
            other (torch.Tensor, float, int, SensitivityTensor): the other tensor or scalar to add to this one.

        """

        # add to a private number
        if isinstance(other, SensitivityTensor):

            # perform addition on the raw data (nothing interesting to see here)
            new_vals = self.values + other.values

            # Perhaps the simplest sensitivity calculation. If two entities add two values together, then
            # the maximum value of the result is the sum of the maximum possible value of each of the inputs.
            # Note that if multiple entities contributed to each of the variables, then each entity's maximum
            # potential contribution is also summed.

            # Multiplication by .entities merely masks out entities which aren't being used.
            new_max_ent_conts = (self.max_ent_conts * self.entities) + (
                other.max_ent_conts * other.entities
            )

            # Similarly, if two entities add two values together, then the minimum value that the result could
            # take on is simply the sum of the minimum values of the inputs. If multiple entities contributed
            # to each of the input variables, then each entitiy's maximum negative contribution is also summed

            # Multiplication by .entities merely masks out entities which aren't being used.
            new_min_ent_conts = (self.min_ent_conts * self.entities) + (
                other.min_ent_conts * other.entities
            )

        else:
            # add to a public number
            new_vals = self.values + other

            # If the value of `other' is not a SensitivityTensor, then we assume that it is public and has a max_val
            # and min_val set at exactly the data, which we can use to sum with the current self.max_ent_conts and
            # self.min_ent_conts. We ignore self.entities because we can without meaningfully changing the result.
            new_max_ent_conts = self.max_ent_conts + other
            new_min_ent_conts = self.min_ent_conts + other

        return SensitivityTensor(
            values=new_vals, max_ent_conts=new_max_ent_conts, min_ent_conts=new_min_ent_conts
        )

    def __mul__(self, other):
        """Multipli es self by either another SensitivityTensor or a scalar or a tensor of equal size.

        Args:
            other (torch.Tensor, float, int, SensitivityTensor): the other tensor or scalar to multiply to this one.

        """

        # if the other tensor is a scalar TODO: add support for arbitrary torch tensors (which should work)
        if not isinstance(other, SensitivityTensor):

            # add to a public number
            new_vals = self.values * other

            # if the scalar is greater than 0, then we proceed as normal
            if other > 0:
                new_max_ent_conts = self.max_ent_conts * other
                new_min_ent_conts = self.min_ent_conts * other

            # if the scalar is negative, then it means it's going to flip the sign which means we need to flip
            # the position of min/max val as well because they're going to jump to the opposite sides of 0 (which means
            # for example, if other == -1, the max value would actually become the (-1 * min) and vise versa)
            else:
                new_min_ent_conts = self.max_ent_conts * other
                new_max_ent_conts = self.min_ent_conts * other

        # if the other tensor is a sensitivty tensor, then we must consider it's max/min values for each entity
        else:

            # just multiplying the values... nothing to see here
            new_vals = self.values * other.values

            # Step 1: calculate the new maximum value for each entity in self's ancestry.
            # Since this could be the product of two large positive numbers
            # or two large negative numbers. We must calculate the product of the (potentially)
            # largest positive values (potentially) largest negative values and then take the max between them.

            # Step 1A: each entity's contribution to self (positive or negative) could potentially be scaled by as much as the
            # maximum possible value of the other value given all other.entities. Aka - if Bob has x within the range
            # [0, 1], and y was created by Alice and Jim with ranges [0,2], and [1,3], then Bob's contribution to the
            # result could be scaled by (2 + 3). Thus, bob's potential contribution to the result is 1 * (2 + 3) = 6.
            # Note: the example above is just for one value - but we're doing it for all self.values elementwise.
            self_max_other_max = self.max_ent_conts * other.expanded_max_vals

            # Step 1B: Same as self_max_other_max except we do it between minimum values on the off chance that they're both
            # negative and greater in magnitude than the positive ones.
            self_min_other_min = self.min_ent_conts * other.expanded_min_vals

            # Step 1C: the greater between the multiplied max and multiplied min, returning the maximum possible amount each
            # entity in self could have contributed to the result.
            new_self_max_ent_conts = th.max(self_min_other_min, self_max_other_max)

            # Step 2: calculate the new minimum value for each entity in self's ancestry

            # Same as Step 1A but for calculating the minimum - we compare min/max in case self.max and other.min have
            # opposite signs
            self_max_other_min = self.max_ent_conts * other.expanded_min_vals

            # Same as Step 1B but for calculating the minimum - we compare min/max in case self.min and other.max have
            # opposit signs
            self_min_other_max = self.min_ent_conts * other.expanded_max_vals

            # Same as Step 1C but for calculating the minimum - although we also compare it to self_min_other_min
            # on the off chance that the minimums for both self and other are both positive.
            new_self_min_ent_conts = th.min(
                th.min(self_min_other_max, self_max_other_min), self_min_other_min
            )

            # Step 3: repeat step 1 and 2 but for the entities in 'other' instead. We need to do this because the
            # multiplication of an entities max/min val by the overall max/min value over all entities is not
            # symmetric.

            other_min_self_min = other.min_ent_conts * self.expanded_min_vals
            other_max_self_max = other.max_ent_conts * self.expanded_max_vals
            new_other_max_ent_conts = th.max(other_min_self_min, other_max_self_max)

            other_min_self_max = other.min_ent_conts * self.expanded_max_vals
            other_max_self_min = other.max_ent_conts * self.expanded_min_vals
            new_other_min_ent_conts = th.max(
                other_min_self_max, other_max_self_min, other_min_self_min
            )

            # Step 4: additively combine max values across entities from both self and other

            # Step 4A: compute the union between entities from self and other
            entities_self_or_other = (self.entities + other.entities) > 0

            # Step 4B: Set any self_max_ent_conts to be the smallest representable number for entities not in self's ancestry
            new_self_max_ent_conts = (new_self_max_ent_conts * self.entities) + (
                (1 - self.entities) * -max_long
            )

            # Step 4C: Set any other_max_ent_conts to be the smallest representable number for entities not in other's ancestry
            new_other_max_ent_conts = (new_other_max_ent_conts * self.entities) + (
                (1 - other.entities) * -max_long
            )

            # Step 4D: Set new max ent conts for result. Note that Step 4b and 4c make it so that assymetric entitiy
            # usage (where self has a different but overlapping ancestry from other) across self and other is
            # properly handled
            new_max_ent_conts = (
                th.max(new_self_max_ent_conts, new_other_max_ent_conts) * entities_self_or_other
            )

            # Step 5: additively combine min values across entities from both self and other

            # Step 5A: Set any self_min_ent_conts to be the largest representable number for entities not in self's ancestry
            new_self_min_ent_conts = (new_self_min_ent_conts * self.entities) + (
                (1 - self.entities) * max_long
            )

            # Step 5B: Set any other_min_ent_conts to be the largest representable number for entities not in other's ancestry
            new_other_min_ent_conts = (new_other_min_ent_conts * self.entities) + (
                (1 - other.entities) * max_long
            )

            # Step 5C: set result minimum entity contributions for result. Note that Step 4b and 4c make it so that
            # assymetric entitiy usage (where self has a different but overlapping ancestry from other) across self
            #  and other is properly handled
            new_min_ent_conts = (
                th.min(new_self_min_ent_conts, new_other_min_ent_conts) * entities_self_or_other
            )

        return SensitivityTensor(new_vals, new_max_ent_conts, new_min_ent_conts)

    def __neg__(self):
        """Flips the sign of all values in the underlying tensor - tracking sensitivity accordingly"""

        # note that new_min_ent_conts and new_max_ent_conts are reversed intentionally because the sign is being
        # flipped. For example, a tensor with range (-1, 3) would be flipped to (-3, 1).
        return SensitivityTensor(-self.values, -self.min_ent_conts, -self.max_ent_conts)

    def __sub__(self, other):

        # add to a private number
        if isinstance(other, SensitivityTensor):

            # just telling the data to do subtraction... nothing to see here
            new_vals = self.values - other.values

            # note that other.max/min values are reversed on purpose
            # because this functionality is equivalent to
            # output = self + (other * -1) and multiplication by
            # a negative number swaps the max/min values with each
            # other and flips their sign

            # similar to __add__ but with
            new_max_ent_conts = (self.entities * self.max_ent_conts) - (
                other.entities * other.min_ent_conts
            )
            new_min_ent_conts = (self.entities * self.min_ent_conts) - (
                other.entities * other.max_ent_conts
            )

        else:
            # add to a public number
            new_vals = self.values - other
            new_max_ent_conts = self.max_ent_conts - other
            new_min_ent_conts = self.min_ent_conts - other

        return SensitivityTensor(new_vals, new_max_ent_conts, new_min_ent_conts)

    def __truediv__(self, other):

        if isinstance(other, SensitivityTensor):
            raise Exception("probably best not to do this - it's gonna be inf a lot")

        new_vals = self.values / other
        new_max_ent_conts = self.max_ent_conts / other
        new_min_ent_conts = self.min_ent_conts / other

        return SensitivityTensor(new_vals, new_max_ent_conts, new_min_ent_conts)

    def __gt__(self, other):
        """BUG: the zero values mess this up"""
        if isinstance(other, SensitivityTensor):

            new_vals = self.values > other.values

            # if self is bigger than the biggest possible other
            if_left = (self.min_ent_conts > other.expanded_max_vals).float() * self.entities

            # if self is smaller than the smallest possible other
            if_right = (self.max_ent_conts < other.expanded_min_vals).float() * self.entities

            # if self doesn't overlap with other at all
            if_left_or_right = if_left + if_right  # shouldn't have to check if this > 2 assuming
            # other's max is > other's min

            # if self does overlap with other
            new_self_max_ent_conts = 1 - if_left_or_right

            # can't have a threshold output less than 0
            new_self_min_ent_conts = if_left_or_right * 0

            # if other is bigger than the smallest possible self
            if_left = (other.min_ent_conts > self.expanded_max_vals).float() * other.entities

            # if other is smaller than the smallest possible self
            if_right = (other.max_ent_conts < self.expanded_min_vals).float() * other.entities

            # if other and self don't overlap
            if_left_or_right = if_left + if_right  # shouldn't have to check if this > 2 assuming
            # other's max is > other's min

            # if other and self do overlap
            new_other_max_ent_conts = 1 - if_left_or_right

            # the smallest possible result is 0
            new_other_min_ent_conts = new_self_min_ent_conts + 0

            # only contribute information from entities in ancestry
            new_self_max_ent_conts = (new_self_max_ent_conts * self.entities) + (
                (1 - self.entities) * -max_long
            )
            new_other_max_ent_conts = (new_other_max_ent_conts * self.entities) + (
                (1 - self.entities) * -max_long
            )

            # only contribute information from entities in ancestry
            new_self_min_ent_conts = (new_self_min_ent_conts * self.entities) + (
                (1 - self.entities) * max_long
            )
            new_other_min_ent_conts = (new_other_min_ent_conts * self.entities) + (
                (1 - self.entities) * max_long
            )

            entities_self_or_other = ((self.entities + other.entities) > 0).float()

            new_max_val = (
                th.max(new_self_max_ent_conts, new_other_max_ent_conts) * entities_self_or_other
            )
            new_min_val = (
                th.min(new_self_min_ent_conts, new_other_min_ent_conts) * entities_self_or_other
            )

        else:

            new_vals = self.values > other

            if_left = other <= self.max_ent_conts
            if_right = other >= self.min_ent_conts
            if_and = if_left * if_right

            new_max_val = if_and
            new_min_val = new_max_val * 0

        return SensitivityTensor(new_vals, new_max_val, new_min_val)

    def __lt__(self, other):
        return other.__gt__(self)

    def clamp_min(self, other):

        if isinstance(other, SensitivityTensor):
            raise Exception("Not implemented yet")

        new_min_val = self.min_ent_conts.clamp_min(other)

        return SensitivityTensor(self.values.clamp_min(other), self.max_ent_conts, new_min_val)

    def clamp_max(self, other):

        if isinstance(other, SensitivityTensor):
            raise Exception("Not implemented yet")

        new_max_val = self.max_ent_conts.clamp_max(other)

        return SensitivityTensor(self.values.clamp_max(other), new_max_val, self.min_ent_conts)

    @property
    def max_vals(self):
        """This returns the maximum possible value over all entities"""

        return (self.max_ent_conts * self.entities).sum(1)

    @property
    def expanded_max_vals(self):
        return self.max_vals.unsqueeze(1).expand(self.max_ent_conts.shape)

    @property
    def min_vals(self):
        """This returns the minimum possible values over all entities"""

        return (self.min_ent_conts * self.entities).min(1)[0]

    @property
    def expanded_min_vals(self):
        return self.min_vals.unsqueeze(1).expand(self.min_ent_conts.shape)

    @property
    def sensitivity(self):
        return (self.max_ent_conts - self.min_ent_conts).sum(1)

    @property
    def entities(self):
        return self._entities

    @entities.setter
    def entities(self, x):
        self._entities = x.float()

    def hard_sigmoid(self):
        return self.min(1).max(0)

    def hard_sigmoid_deriv(self, leak=0.01):
        return ((self < 1) * (self > 0)) + (self < 0) * leak - (self > 1) * leak
